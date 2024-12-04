
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

4. Must run image in privileged mode
```
docker run --privileged -it europe-west2-docker.pkg.dev/anton-390822/swe-bench/swe-test:latest
```




So, seems like Google Compute Engine has a Docker base, which we may be able to use docker pull from?


# So this shit works. As in, GCP compute engine has a docker base, which we may be able to use docker pull from?
docker run -v -d /var/run/docker.sock:/var/run/docker.sock <image_name>