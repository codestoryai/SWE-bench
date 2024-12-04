
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
