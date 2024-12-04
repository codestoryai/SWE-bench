
1. Tag the image
Usage: `docker tag <local_image_name> europe-west2-docker.pkg.dev/anton-390822/swe-bench/<image_name>:<tag>`
```
docker tag swe_test europe-west2-docker.pkg.dev/anton-390822/swe-bench/swe-test:latest
```

2. Push the image
```
docker push europe-west2-docker.pkg.dev/anton-390822/swe-bench/swe-test:latest
```

3. Check for its existence
```
gcloud artifacts docker images list europe-west2-docker.pkg.dev/anton-390822/swe-bench
```

4. Configure VM to use the new image
Do so in the Google Cloud Compute Engine VM Instance. Section: Container

5. SSH into the VM

6. Get image ID
```
docker images
```
7. Run the image manually with the following command:
```
docker run -d -v /var/run/docker.sock:/var/run/docker.sock <image_id>
```

8. Exec into the container
```
docker exec -it <container_id> sh
```

9. Activate the venv
```
. venv/bin/activate
```

# docker run --privileged -d <image_id>