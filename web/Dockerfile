FROM node:22.17.0-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Empty by default: nginx below proxies /v1 to the API on the same origin.
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginx:1.29.0-alpine
# Pick up Alpine security fixes released after the base image was built.
RUN apk upgrade --no-cache
# nginx renders templates with envsubst at start-up (only ${PUBLIC_ORIGIN} is an
# environment variable in this file; nginx's own $variables are left alone).
ENV PUBLIC_ORIGIN=""
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
