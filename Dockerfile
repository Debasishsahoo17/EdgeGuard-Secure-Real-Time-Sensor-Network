FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && groupadd --system edgeguard \
 && useradd --system --gid edgeguard edgeguard \
 && mkdir -p /app/data \
 && chown -R edgeguard:edgeguard /app
COPY --chown=edgeguard:edgeguard edgeguard/ ./edgeguard/
COPY --chown=edgeguard:edgeguard web/ ./web/
USER edgeguard
EXPOSE 8080
CMD ["python", "-m", "edgeguard", "gateway"]
