# Docker Build Files

This folder contains Dockerfiles used by Compose, CI, and deployment scripts.

- `Dockerfile.service` builds backend and AI service containers.
- `Dockerfile.ui` builds the React UI and Nginx runtime image.

The root `docker-compose*.yml` files stay at the repository root because local, CI, and VM scripts invoke them from there.
