ARG NODE_IMAGE=docker.m.daocloud.io/library/node:22-slim
FROM ${NODE_IMAGE}

WORKDIR /app

COPY MetaRec-ui/package*.json ./
RUN npm ci

COPY MetaRec-ui/ ./

EXPOSE 5173

# Mirrors the compose command: reconcile deps against the (possibly stale)
# node_modules volume before starting the dev server.
CMD ["sh", "-c", "npm install --prefer-offline --no-audit --no-fund && npm run dev -- --host 0.0.0.0"]
