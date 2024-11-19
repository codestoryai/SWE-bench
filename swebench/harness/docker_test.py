import docker

if __name__ == '__main__':
    client = docker.from_env()
    print(client.images.list())
    try:
        image = client.images.get('swebench/sweb.eval.x86_64.django_1776_django-13033:v1')
        print(image)
    except Exception as e:
        print(e)