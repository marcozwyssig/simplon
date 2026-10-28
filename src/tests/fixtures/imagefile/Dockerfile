# si#552: the image test_imagefile_e2e.py builds for linux/amd64 and linux/arm64 and copies files out of.
# /hello is static, so it runs in imagefile.FILE_TEST_IMAGE (busybox on musl, no loader); /hello-dynamic is
# the same source linked against musl dynamically, so its loader is absent there and it is red. /adir is a
# directory, which build:image-file refuses. Every base is pinned by its index digest.
FROM alpine:3.22@sha256:2e0b81d60597f449baa56dc25d355367869d2dca4cd57e866f1e2b52af3eb55f AS build
ARG VERSION=unset
RUN apk add --no-cache gcc musl-dev
COPY hello.c /src/hello.c
RUN mkdir -p /out \
 && gcc -O2 -static -DVERSION="\"${VERSION}\"" -o /out/hello /src/hello.c \
 && gcc -O2 -DVERSION="\"${VERSION}\"" -o /out/hello-dynamic /src/hello.c \
 && mkdir -p /out/adir \
 && touch /out/adir/inside

FROM scratch
COPY --from=build /out/ /
