FROM gcr.io/distroless/nodejs22-debian13:nonroot
WORKDIR /app
COPY --chown=nonroot:nonroot server.mjs /app/server.mjs
USER nonroot
EXPOSE 3100
ENV NODE_ENV=production PORT=3100
CMD ["server.mjs"]
