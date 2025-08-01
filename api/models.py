from django.db import models

class Song(models.Model):
 
    song_id = models.CharField(max_length=255, primary_key=True)
    title = models.CharField(max_length=255)
    danceability = models.FloatField()
    energy = models.FloatField()
    acousticness = models.FloatField()
    tempo = models.FloatField()
    duration_ms = models.IntegerField()
    num_sections = models.IntegerField()
    num_segments = models.IntegerField()
    rating = models.IntegerField(null=True, blank=True, default=None)
    key = models.IntegerField()
    loudness = models.FloatField()
    mode = models.IntegerField()
    time_signature = models.IntegerField()
    num_bars = models.IntegerField()
    song_class = models.IntegerField()
    instrumentalness = models.FloatField()
    liveness = models.FloatField()
    valence = models.FloatField()

    class Meta:
 
        ordering = ['-rating', 'title']

    def __str__(self):
        """
        String representation of the Song object, useful for Django Admin.
        """
        return f"{self.title} (ID: {self.song_id})"

    def save(self, *args, **kwargs):
        """
        Custom save method to ensure rating is within 1-5 if provided.
        """
        if self.rating is not None and not (1 <= self.rating <= 5):
            raise ValueError("Rating must be between 1 and 5.")
        super().save(*args, **kwargs)

