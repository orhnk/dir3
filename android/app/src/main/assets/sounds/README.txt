Custom alarm sounds
===================

Drop audio files here (mp3, ogg, wav, m4a) and reference them from a plan:

    task("Fajr", start=prayer.fajr, duration="30m",
         alarm=alarm(sound="adhan.mp3", speak=True))

The Android app first looks in this assets/sounds folder, then treats the
value as a content:// URI, then falls back to the system alarm sound.

Use `sound="random"` with `sounds=("adhan.mp3", "adhan2.mp3")` to play one of
several ringtones at random (Clock's random playback).

This file is only documentation; remove it if you like.
