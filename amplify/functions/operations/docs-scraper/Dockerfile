# Meta / external documentation scraper — WECARE.DIGITAL
# Playwright + headless Chromium is far larger than the 250MB zip limit,
# so this Lambda is packaged as a container image (deploy via ECR).
#
# Build context is the repository root (see docs-scraper-deploy.yml) because
# handler.py imports amplify/functions/shared/lambda_utils.
FROM mcr.microsoft.com/playwright/python:v1.64.1-jammy

WORKDIR /var/task

COPY amplify/functions/operations/docs-scraper/requirements.txt ./requirements.txt
# awslambdaric IS PINNED, and the pin is load-bearing rather than tidiness.
#
# It used to be unpinned. On 2026-09-28 at 15:38 UTC, AWS published awslambdaric
# 4.1.0 to PyPI as an sdist with NO wheels at all - 4.0.0 shipped nineteen files
# including manylinux2014_x86_64 wheels for cp39 through cp314; 4.1.0 shipped one
# tarball. The next build of this image started two and a half minutes later, pip
# selected 4.1.0, found nothing prebuilt, and fell back to compiling from source.
# That runs the sdist's scripts/preinstall.sh, which needs cmake, which this
# Playwright base image does not carry:
#
#   Error: cmake is not installed.
#   ERROR: Failed to build 'awslambdaric' when getting requirements to build wheel
#
# So an unpinned dependency turned a third party's release into a red deploy for
# this repository, with no change on our side. Nothing about the runner or the
# base image moved. Pinning to 4.0.0 - the newest release that publishes a
# manylinux x86_64 wheel - means pip installs a binary and never invokes a
# compiler, so the build does not depend on cmake being present.
#
# Before raising this pin, check that the target version actually publishes a
# wheel for this image's Python and architecture. If a future version is
# sdist-only by design, the alternative is `apt-get install -y cmake` above this
# line, which costs build time on every layer rebuild to gain nothing else.
RUN pip install --no-cache-dir -r requirements.txt awslambdaric==4.0.0

# Chromium is included in the Playwright image; this keeps the browser version
# aligned with the Python Playwright package.
RUN python -m playwright install chromium

COPY amplify/functions/operations/docs-scraper/handler.py ./handler.py
COPY amplify/functions/shared/lambda_utils ./lambda_utils

ENTRYPOINT ["python", "-m", "awslambdaric"]
CMD ["handler.lambda_handler"]
