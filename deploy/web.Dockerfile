FROM node:22.14.0-bookworm-slim AS build
WORKDIR /web
COPY frontend/web/package.json frontend/web/package-lock.json ./
RUN npm ci
COPY frontend/web/ ./
RUN npm run build

FROM nginx:1.28.0-alpine
COPY deploy/nginx.conf /etc/nginx/nginx.conf
COPY --from=build /web/dist /usr/share/nginx/html
USER nginx
ENTRYPOINT ["nginx"]
CMD ["-g", "daemon off;"]
