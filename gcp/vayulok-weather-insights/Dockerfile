FROM node:26-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY package.json server.mjs weather-data.mjs aggregate.mjs ./
USER node
CMD ["node", "server.mjs"]
