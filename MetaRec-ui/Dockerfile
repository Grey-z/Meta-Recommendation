ARG NODE_IMAGE=docker.m.daocloud.io/library/node:22-slim
FROM ${NODE_IMAGE}

WORKDIR /app

COPY MetaRec-ui/package*.json ./
RUN npm ci

COPY MetaRec-ui/ ./

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
