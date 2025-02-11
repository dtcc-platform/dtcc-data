nohup uvicorn server-gpkg-ssh:app --host 0.0.0.0 --port 8001 --workers=4 &
nohup uvicorn server-lidar-ssh:app --host 0.0.0.0 --port 8000 --workers=4 &
