# PR 16: Docker CI

Adds a new job to the GitHub Actions workflow `ci.yml` that builds the Docker image and tests that it runs correctly by executing `python manage.py check` inside the container.
