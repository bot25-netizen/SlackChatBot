# Dockerfile

# ベースとなるPythonのバージョンを指定
FROM python:3.11-slim

# 環境変数を設定（Pythonのログがバッファされず、すぐに見れるようにする）
ENV PYTHONUNBUFFERED 1

ENV PORT=800

# アプリケーションを格納する作業ディレクトリを作成
WORKDIR /app

# 必要なライブラリのリストをコピー
COPY requirements.txt .

# ライブラリをインストール
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir slack_bolt aiohttp

# プロジェクトの全てのファイルを作業ディレクトリにコピー
COPY . .

# アプリケーションを実行（Koyebが指定するポートで起動）
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

