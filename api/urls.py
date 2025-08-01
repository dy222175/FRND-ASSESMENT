from django.urls import path
from . import views  

urlpatterns = [
 
    path('songs/', views.SongListAPIView.as_view(), name='song-list'),

    path('songs/search/', views.SongSearchAPIView.as_view(), name='song-search'),

    path('songs/rate/', views.RateSongAPIView.as_view(), name='song-rate'),
 
    path('songs/upload-json/', views.JsonUploadAPIView.as_view(), name='song-upload-json'),
]

