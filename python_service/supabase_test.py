import os
from supabase import create_client, Client

url: str = "https://accsggfozblvqloehver.supabase.co"
key: str = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFjY3NnZ2ZvemJsdnFsb2VodmVyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjU1NzAxNDksImV4cCI6MjA4MTE0NjE0OX0.idywJPI_z_q9EmYlE-9HsTT9w33q8saJ5ZZJGeppV2E"

supabase: Client = create_client(url, key)

response = supabase.table("users").select("*").execute()
print(response.data)



