import os
import json
import logging
import re
from typing import Dict, Any, List, Optional, Tuple

from django.db import transaction
from django.db.models import F
from django.db import IntegrityError
from django.core.exceptions import ValidationError
from django.core.cache import cache

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework import generics
from rest_framework.parsers import MultiPartParser, FormParser # For file uploads
from rest_framework.status import HTTP_429_TOO_MANY_REQUESTS
import redis
from redis.exceptions import ConnectionError as RedisConnectionError

from .models import Song
from .serializers import SongSerializer

logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


FIELD_DEFAULTS = {
    'duration_ms': 0,
    'num_sections': 0,
    'num_segments': 0,
    'key': 0,
    'mode': 0,
    'time_signature': 4,
    'num_bars': 0,
    'song_class': 0,
    'danceability': 0.0,
    'energy': 0.0,
    'acousticness': 0.0,
    'tempo': 120.0,
    'loudness': -60.0,
    'instrumentalness': 0.0,
    'liveness': 0.0,
    'valence': 0.0,
    'title': "Untitled Song",
    'rating': None,
}

VALIDATION_RULES = {
    'rating': {'min': 1, 'max': 5, 'message': 'Rating must be between 1 and 5'},
    'duration_ms': {'min': 0, 'message': 'Duration must be positive'},
    'tempo': {'min': 0, 'max': 300, 'message': 'Tempo must be between 0 and 300 BPM'},
    'loudness': {'min': -60, 'max': 0, 'message': 'Loudness must be between -60 and 0 dB'},
    'danceability': {'min': 0.0, 'max': 1.0, 'message': 'Danceability must be between 0.0 and 1.0'},
    'energy': {'min': 0.0, 'max': 1.0, 'message': 'Energy must be between 0.0 and 1.0'},
    'acousticness': {'min': 0.0, 'max': 1.0, 'message': 'Acousticness must be between 0.0 and 1.0'},
    'instrumentalness': {'min': 0.0, 'max': 1.0, 'message': 'Instrumentalness must be between 0.0 and 1.0'},
    'liveness': {'min': 0.0, 'max': 1.0, 'message': 'Liveness must be between 0.0 and 1.0'},
    'valence': {'min': 0.0, 'max': 1.0, 'message': 'Valence must be between 0.0 and 1.0'},
}

MAX_FILE_SIZE = 10 * 1024 * 1024

REDIS_HOST = os.environ.get('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.environ.get('REDIS_PORT', 6379))
REDIS_DB = int(os.environ.get('REDIS_DB', 0))

redis_client = None
try:
    redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
    redis_client.ping()
    logging.info(f"Successfully connected to Redis at {REDIS_HOST}:{REDIS_PORT}.")
except RedisConnectionError as e:
    logging.warning(f"Could not connect to Redis at {REDIS_HOST}:{REDIS_PORT}: {e}. Running without Redis cache.")
    redis_client = None
 
class StandardResultsPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'limit'
    max_page_size = 100

def cache_all_songs_sorted(songs_queryset):
    if not redis_client:
        return

    try:
        pipeline = redis_client.pipeline()
        pipeline.delete("songs_by_rating")

        for song in songs_queryset:
            serializer = SongSerializer(song)
            song_data = serializer.data
            song_id = song_data["song_id"]
            rating_score = song_data.get("rating") if song_data.get("rating") is not None else 0

            pipeline.set(f"song:{song_id}", json.dumps(song_data))
            pipeline.zadd("songs_by_rating", {song_id: rating_score})
        pipeline.execute()
        logging.info(f"Cached {len(songs_queryset)} songs in Redis sorted set 'songs_by_rating'.")
    except Exception as e:
        logging.error(f"Error caching all songs in Redis: {e}")

def get_cached_all_songs_sorted():
    if not redis_client:
        return None
    try:
        song_ids = redis_client.zrevrange("songs_by_rating", 0, -1)
        if not song_ids:
            return None

        cached_songs_data = []
        for song_id in song_ids:
            song_data_str = redis_client.get(f"song:{song_id}")
            if song_data_str:
                cached_songs_data.append(json.loads(song_data_str))
        logging.info(f"Fetched {len(cached_songs_data)} songs from Redis cache.")
        return cached_songs_data
    except Exception as e:
        logging.error(f"Error retrieving cached songs from Redis: {e}")
        return None

def update_song_cache(song_instance):
    if not redis_client:
        return

    try:
        serializer = SongSerializer(song_instance)
        song_data = serializer.data
        song_id = song_data["song_id"]
        rating_score = song_data.get("rating") if song_data.get("rating") is not None else 0

        redis_client.set(f"song:{song_id}", json.dumps(song_data))
        redis_client.zadd("songs_by_rating", {song_id: rating_score})
        logging.info(f"Updated cache for song_id: {song_id} with new rating: {rating_score}.")
    except Exception as e:
        logging.error(f"Error updating song cache for {song_instance.song_id}: {e}")

def _normalize_column_oriented_json_data(data_dict):
    """
    Transforms column-oriented JSON data (like playlist[76].json)
    into a list of row-oriented song dictionaries.
    This version explicitly maps each field and provides defaults for missing/None values
    to prevent 'NoneType' errors and ensure non-nullable fields have a value.
    """
    normalized_records = []
    num_songs = len(data_dict.get("id", {}))
    
    json_to_model_map = {
        "id": "song_id",
        "title": "title",
        "danceability": "danceability",
        "energy": "energy",
        "acousticness": "acousticness",
        "tempo": "tempo",
        "duration_ms": "duration_ms",
        "num_sections": "num_sections",
        "num_segments": "num_segments",
        "key": "key",
        "loudness": "loudness",
        "mode": "mode",
        "time_signature": "time_signature",
        "num_bars": "num_bars",
        "class": "song_class",
        "instrumentalness": "instrumentalness",
        "liveness": "liveness",
        "valence": "valence",
    }

    for i in range(num_songs):
        song_record = {}
        idx_str = str(i)  

        for json_key, model_field in json_to_model_map.items():

            value = data_dict.get(json_key, {}).get(idx_str)
            if isinstance(value, str):
                value = value.strip()
 
            if value is None and model_field in FIELD_DEFAULTS:
                value = FIELD_DEFAULTS[model_field]
                logging.debug(f"Applied default '{value}' for missing/None field '{model_field}' at index {i}.")

            song_record[model_field] = value

        song_record['rating'] = FIELD_DEFAULTS.get('rating', None)
 
        if not song_record.get("song_id") or not song_record.get("title"):
            raw_song_data_for_index = {k: data_dict.get(k, {}).get(idx_str) for k in data_dict.keys()}
            logging.warning(f"Skipping song at index {i} due to missing 'song_id' or 'title' after normalization. Raw data: {raw_song_data_for_index}")
            continue  

        normalized_records.append(song_record)
    return normalized_records


# --- API Endpoints ---
class SongListAPIView(APIView):
 
    pagination_class = StandardResultsPagination

    def get(self, request, *args, **kwargs):
        try:
            paginator = self.pagination_class()
            songs_data = get_cached_all_songs_sorted()

            if songs_data:
                logging.info("Serving songs from Redis cache.")
                paginated_songs = paginator.paginate_queryset(songs_data, request)
                return paginator.get_paginated_response(paginated_songs)

            else:
                logging.info("Fetching songs from database because redis cache missed.")
                queryset = Song.objects.all().order_by('-rating')  

                cache_all_songs_sorted(queryset)
                songs_data_after_db_fetch = get_cached_all_songs_sorted()

                if songs_data_after_db_fetch:
                    paginated_songs = paginator.paginate_queryset(songs_data_after_db_fetch, request)
                    return paginator.get_paginated_response(paginated_songs)
                else:
                    logging.warning("Failed to retrieve from cache even after populating. Serving directly from DB queryset.")
                    paginated_queryset = paginator.paginate_queryset(queryset, request)
                    serializer = SongSerializer(paginated_queryset, many=True)
                    return paginator.get_paginated_response(serializer.data)

        except Exception as e:
            logging.error(f"Error retrieving songs: {e}", exc_info=True)
            return Response({
                "status": "error",
                "data": {
                    "message": "Unable to retrieve songs"
                }
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SongSearchAPIView(generics.ListAPIView):
 
    serializer_class = SongSerializer

    def get_queryset(self):
        title = self.request.query_params.get('title', None)
        if title:
            return Song.objects.filter(title__icontains=title).order_by('-rating', 'title')
        return Song.objects.none()

    def list(self, request, *args, **kwargs):
        try:
            title = request.query_params.get('title', '').strip()
            
            if not title:
                return Response({
                    "status": "error",
                    "data": {
                        "message": "Search term is required"
                    }
                }, status=status.HTTP_400_BAD_REQUEST)

            queryset = self.get_queryset()
            
            if not queryset.exists():
                return Response({
                    "status": "error",
                    "data": {
                        "search_term": title,
                        "total_results": 0,
                        "message": "No songs found matching the title"
                    }
                }, status=status.HTTP_404_NOT_FOUND)
            
            serializer = self.get_serializer(queryset, many=True)
            return Response({
                "status": "success",
                "data": {
                    "search_term": title,
                    "total_results": len(serializer.data),
                    "results": serializer.data
                }
            })
            
        except Exception as e:
            logging.error(f"Error during song search: {e}", exc_info=True)
            return Response({
                "status": "error",
                "data": {
                    "message": "Search failed"
                }
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class RateSongAPIView(APIView):
    """
    API endpoint to allow users to rate a song (1-5 stars).
    PUT /api/songs/rate
    Request Payload: {"song_id": "song123", "rating": 4}
    """
    def put(self, request, *args, **kwargs):
        try:
            song_id = request.data.get('song_id')
            
            if not song_id:
                return Response({
                    "status": "error",
                    "data": {
                        "message": "song_id is required in payload"
                    }
                }, status=status.HTTP_400_BAD_REQUEST)
            
            user_key = f"rate_limit_{request.user.id if hasattr(request, 'user') else 'anonymous'}_{song_id}"
            current_attempts = cache.get(user_key, 0)
            
            if current_attempts >= 10:
                return Response({
                    "status": "error",
                    "data": {
                        "message": "Rate limit exceeded. Please wait before rating this song again."
                    }
                }, status=status.HTTP_429_TOO_MANY_REQUESTS)
            
            cache.set(user_key, current_attempts + 1, 60)   
            
            rating = request.data.get('rating')
            
            if rating is None:
                return Response({
                    "status": "error",
                    "data": {
                        "message": "Rating is required"
                    }
                }, status=status.HTTP_400_BAD_REQUEST)
            
            try:
                rating = int(rating)
            except (ValueError, TypeError):
                return Response({
                    "status": "error",
                    "data": {
                        "message": "Rating must be a number between 1 and 5"
                    }
                }, status=status.HTTP_400_BAD_REQUEST)
            
            if not (1 <= rating <= 5):
                return Response({
                    "status": "error",
                    "data": {
                        "message": "Rating must be between 1 and 5"
                    }
                }, status=status.HTTP_400_BAD_REQUEST)

            with transaction.atomic():
                try:
                    song = Song.objects.get(pk=song_id)
                    old_rating = song.rating
                    song.rating = rating
                    song.save()

                    update_song_cache(song)
                    logging.info(f"Updated rating for song {song_id}: {old_rating} → {rating}")

                    serializer = SongSerializer(song)
                    response_data = serializer.data
                    response_data.update({
                        "rating_change": f"{old_rating} → {rating}" if old_rating is not None else f"None → {rating}",
                        "song_id": song_id
                    })
                    return Response({
                        "status": "success",
                        "data": response_data
                    })

                except Song.DoesNotExist:
                    return Response({
                        "status": "error",
                        "data": {
                            "message": "Song not found",
                            "song_id": song_id
                        }
                    }, status=status.HTTP_404_NOT_FOUND)
                except ValueError as e:
                    return Response({
                        "status": "error",
                        "data": {
                            "message": str(e)
                        }
                    }, status=status.HTTP_400_BAD_REQUEST)
                
        except Exception as e:
            logging.error(f"Error rating song {song_id}: {e}", exc_info=True)
            return Response({
                "status": "error",
                "data": {
                    "message": "An internal server error occurred"
                }
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class JsonUploadAPIView(APIView):
 
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request, *args, **kwargs):
        if 'file' not in request.FILES:
            return Response({
                "status": "error",
                "data": {
                    "message": "No file uploaded"
                }
            }, status=status.HTTP_400_BAD_REQUEST)

        uploaded_file = request.FILES['file']

        if not uploaded_file.name.endswith('.json'):
            return Response({
                "status": "error",
                "data": {
                    "message": "Invalid file type. Only .json files are allowed"
                }
            }, status=status.HTTP_400_BAD_REQUEST)

        if uploaded_file.size > MAX_FILE_SIZE:
            return Response({
                "status": "error",
                "data": {
                    "message": f"File too large. Maximum size is {MAX_FILE_SIZE / (1024 * 1024)}MB"
                }
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            raw_json_data = json.loads(uploaded_file.read())
            data_to_process = []
 
            if isinstance(raw_json_data, list) and len(raw_json_data) == 1 and isinstance(raw_json_data[0], dict) and 'id' in raw_json_data[0]:
                logging.info("Detected list containing single column-oriented JSON object. Normalizing data.")
                data_to_process = _normalize_column_oriented_json_data(raw_json_data[0])
            else:
                return Response({
                    "status": "error",
                    "data": {
                        "message": "JSON file must contain a list of song objects or a single column-oriented object"
                    }
                }, status=status.HTTP_400_BAD_REQUEST)
            
            processed_count = 0
            skipped_count = 0
            errors = []

            with transaction.atomic():
                for index, song_data_raw in enumerate(data_to_process):
                    try:
                        song_data = song_data_raw.copy()

                        if 'song_id' in song_data and isinstance(song_data['song_id'], str):
                            song_data['song_id'] = song_data['song_id'].strip()

                        integer_fields = ['duration_ms', 'num_sections', 'num_segments', 'key', 
                                        'mode', 'time_signature', 'num_bars', 'song_class']
                        
                        for field_name in integer_fields:
                            value = song_data.get(field_name)
                            if value is None:
                                song_data[field_name] = FIELD_DEFAULTS.get(field_name, 0)
                            else:
                                try:
                                    song_data[field_name] = int(value)
                                except (ValueError, TypeError):
                                    logging.warning(f"Could not convert {field_name} ('{value}') to int for song {song_data.get('song_id', 'N/A')}. Using default.")
                                    song_data[field_name] = FIELD_DEFAULTS.get(field_name, 0)
 
                        float_fields = ['danceability', 'energy', 'acousticness', 'tempo', 
                                      'loudness', 'instrumentalness', 'liveness', 'valence']
                        
                        for field_name in float_fields:
                            value = song_data.get(field_name)
                            if value is None:
                                song_data[field_name] = FIELD_DEFAULTS.get(field_name, 0.0)
                            else:
                                try:
                                    song_data[field_name] = float(value)
                                except (ValueError, TypeError):
                                    logging.warning(f"Could not convert {field_name} ('{value}') to float for song {song_data.get('song_id', 'N/A')}. Using default.")
                                    song_data[field_name] = FIELD_DEFAULTS.get(field_name, 0.0)

                        if ('title' not in song_data or 
                            not isinstance(song_data['title'], str) or 
                            not song_data['title'].strip()):
                            song_data['title'] = "Untitled Song"
                            logging.warning(f"Song at index {index + 1} has missing or invalid title. Using default.")

                        if 'rating' not in song_data:
                            song_data['rating'] = FIELD_DEFAULTS.get('rating', None)
                        elif song_data['rating'] is not None:
                            try:
                                rating_value = int(song_data['rating'])
                                if not (1 <= rating_value <= 5):
                                    logging.warning(f"Invalid rating {rating_value} for song {song_data.get('song_id', 'N/A')}. Setting to None.")
                                    song_data['rating'] = None
                                else:
                                    song_data['rating'] = rating_value
                            except (ValueError, TypeError):
                                logging.warning(f"Could not convert rating to int for song {song_data.get('song_id', 'N/A')}. Setting to None.")
                                song_data['rating'] = None

                        logging.debug(f"Attempting to process song_id: '{song_data.get('song_id')}'")

                        song, created = Song.objects.update_or_create(
                            song_id=song_data['song_id'],
                            defaults=song_data
                        )
                        
                        processed_count += 1
                        action = 'Created' if created else 'Updated'
                        logging.info(f"{action} song: {song.title} ({song.song_id}) from JSON upload.")

                    except IntegrityError as ie:
                        skipped_count += 1
                        song_id = song_data_raw.get('song_id', 'N/A')
                        error_msg = f"Row {index + 1} (song_id: {song_id}): Integrity error - {ie}. This song ID might already exist or a NOT NULL field is missing."
                        errors.append(error_msg)
                        logging.warning(error_msg)

                    except Exception as e:
                        skipped_count += 1
                        song_id = song_data_raw.get('song_id', 'N/A')
                        error_msg = f"Row {index + 1} (song_id: {song_id}): Error processing - {e}"
                        errors.append(error_msg)
                        logging.error(f"Error processing row {index + 1} from JSON: {e}", exc_info=True)

            logging.info("Re-caching all songs after JSON upload to ensure sorted list is fresh.")
            cache_all_songs_sorted(Song.objects.all())

            response_data = {
                "processed_records": processed_count,
                "skipped_records": skipped_count,
                "total_records": processed_count + skipped_count
            }
            
            if errors:
                response_data["errors"] = errors[:10]
            
            return Response({
                "status": "success",
                "data": response_data
            })

        except json.JSONDecodeError:
            return Response({
                "status": "error",
                "data": {
                    "message": "Invalid JSON file format. Could not decode JSON"
                }
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logging.error(f"Error processing JSON file: {e}", exc_info=True)
            return Response({
                "status": "error",
                "data": {
                    "message": f"An error occurred during file processing: {e}"
                }
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)