import os
import logging
from pathlib import Path
from fastapi import FastAPI, Request
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
import google.generativeai as genai

logging.basicConfig(level=logging.INFO)
app = FastAPI()
slack_app = AsyncApp(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET")
)
slack_handler = AsyncSlackRequestHandler(slack_app)

try:
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    generative_model = genai.GenerativeModel("gemini-2.0-flash")
except KeyError:
    logging.error("環境変数 GEMINI_API_KEY が設定されていません．")
    generative_model = None

# --- 資料情報リスト ---
# documentsフォルダにファイルを追加・削除した場合も、ここのリストを更新すればOK
DOCUMENTS_INFO = [
    {"keyword": "ゼミ", "filename": "zemi_unei.txt", "description": "研究室のゼミのルール、発表者や座長の役割について説明している資料．"},
    {"keyword": "配属後の流れ", "filename": "haizoku_flow.txt", "description": "研究室に新しく配属された学生が、最初に行うべき手続きや活動の流れを説明している資料．"},
    {"keyword": "論文テンプレート", "filename": "ronbun_template.txt", "description": "卒業論文や修士論文を執筆する際のWordテンプレートの使い方や注意点を説明している資料．"},
    {"keyword": "発表の質問例", "filename": "shitsumon_rei.txt", "description": "研究発表の質疑応答でよく聞かれる質問の例をまとめている資料．"},
    {"keyword": "Python教材", "filename": "kyouzai_python.txt", "description": "プログラミング言語Pythonの基本的な学習教材やサイトについて紹介している資料．"},
    {"keyword": "Pytorch教材", "filename": "kyouzai_pytorch.txt", "description": "深層学習フレームワークPytorchの学習教材について紹介している資料．"},
    {"keyword": "機械学習教材", "filename": "kyouzai_machine_learning.txt", "description": "機械学習の全体的な学習教材やライブラリ(scikit-learnなど)について紹介している資料．"},
    {"keyword": "深層学習教材", "filename": "kyouzai_deep_learning.txt", "description": "ディープラーニング（深層学習）の概念や理論に関する学習教材を紹介している資料．"},
    {"keyword": "統計学教材", "filename": "kyouzai_statistics.txt", "description": "統計学の学習教材を紹介している資料．"},
    {"keyword": "線形代数教材", "filename": "kyouzai_linear_algebra.txt", "description": "線形代数の学習教材を紹介している資料．"},
    {"keyword": "自己紹介", "filename": "yourprofile.txt", "description": "AIアシスタント自身の役割や、何ができるかといった自己紹介．"}
]

DOCUMENTS_DIR = Path(__file__).parent / "documents"
doc_keywords = [doc["keyword"] for doc in DOCUMENTS_INFO]

async def get_gemini_response(prompt: str) -> str:
    """Gemini APIを呼び出し、応答を生成する関数"""
    if not generative_model:
        return "Gemini APIキーが設定されていないため、応答できません．"
    try:
        safety_settings = {
            'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE',
            'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE',
            'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE',
            'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE',
        }
        response = await generative_model.generate_content_async(prompt, safety_settings=safety_settings)
        return response.text
    except Exception as e:
        logging.error(f"Gemini API Error: {e}")
        return f"申し訳ありません、AIとの通信中にエラーが発生しました．({e})"

async def send_long_message(client, channel: str, thread_ts: str, text: str):
    """3000字を超えるメッセージを分割してスレッドに投稿する関数"""
    limit = 3000
    if len(text) <= limit:
        await client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=text)
        return
    parts = []
    current_pos = 0
    while current_pos < len(text):
        split_pos = text.rfind("．", current_pos, current_pos + limit)
        if split_pos == -1:
            split_pos = text.rfind("\n", current_pos, current_pos + limit)
        
        if split_pos == -1 or split_pos <= current_pos:
            split_pos = current_pos + limit
        
        parts.append(text[current_pos:split_pos+1])
        current_pos = split_pos + 1
    
    for i, part in enumerate(parts):
        part_text = f"*{i+1}/{len(parts)}*\n\n{part}"
        await client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=part_text)

@app.on_event("startup")
async def startup_event():
    """起動時に資料リストをログに出力する"""
    logging.info(f"以下の資料をキーワードで認識しました: {doc_keywords}")
    if not doc_keywords:
        logging.warning("警告: DOCUMENTS_INFOリストが空です．")
        
@app.get("/health")
async def health_check():
    """Renderのヘルスチェック用"""
    return {"status": "ok"}

@app.post("/slack/events")
async def endpoint(req: Request):
    """Slackからのイベントを受け取る"""
    return await slack_handler.handle(req)

@slack_app.event("app_mention")
@slack_app.event("message")
async def handle_message(event, say, client, context):
    """メンションとDMを処理する"""
    if event.get("bot_id") is not None:
        return
        
    channel_type = event.get("channel_type", "")
    
    if channel_type == 'im' or event['type'] == 'app_mention':
        if event['type'] == 'app_mention':
            user_query = event['text'].replace(f"<@{context['bot_user_id']}>", "").strip()
        else:
            user_query = event['text'].strip()

        if not user_query:
            return

        channel_id = event['channel']
        thread_ts = event.get('thread_ts') or event.get('ts')

        thinking_message = await say(text="🤔 どの資料を読めばいいか考えています...", thread_ts=thread_ts)

        try:

            topic_descriptions = "\n".join([f"- トピック名: {doc['keyword']}\n  説明: {doc['description']}" for doc in DOCUMENTS_INFO])
            classification_prompt = (
                f"あなたはユーザーの質問内容を分析し、最も関連性の高い資料を判断する専門家です．\n"
                f"以下の質問に答えるのに最適なトピックを、下記のトピックリストから一つだけ選び、その「トピック名」だけを答えてください．\n"
                f"もし、どのトピックにも当てはまらない一般知識の質問の場合は、「一般知識」と答えてください．\n\n"
                f"## 質問:\n{user_query}\n\n"
                f"## トピックリスト:\n{topic_descriptions}\n\n"
                f"## 回答（トピック名一つだけ）："
            )
            
            topic = await get_gemini_response(classification_prompt)
            topic = topic.strip().replace("'", "").replace('"', '').replace('．', '').replace('*', '')

            selected_doc_info = next((doc for doc in DOCUMENTS_INFO if doc["keyword"] == topic), None)

            if selected_doc_info:
                selected_file = selected_doc_info["filename"]
                await client.chat_update(
                    channel=channel_id, ts=thinking_message['ts'], text=f"🤔 関連する資料を読んでるよ．ちょっと待ってね"
                )
                
                context_text = (DOCUMENTS_DIR / selected_file).read_text(encoding='utf-8')

                final_query = (
                    f"あなたは研究室の優秀で親しみやすいアシスタント、おくだくんです．\n"
                    f"以下の参考情報に厳密に基づいて、丁寧で分かりやすい言葉で回答を生成してください．\n\n"
                    f"# 指示\n* 箇条書きを使う場合でも、前後に説明の文章を加えて会話のような自然な流れにしてください．\n"
                    f"* 相手は後輩や新入生であることを意識し、親しみやすい口調を心がけてください．\n"
                    f"* 参考情報に書かれていないことは、絶対に答えないでください．\n\n"
                    f"# Slack用の書式ルール\n"
                    f"* 強調したい単語は、`*単語*` のようにアスタリスクで囲んでください．\n"
                    f"* 箇条書きを使う場合は、行頭に `• ` (中黒と半角スペース) を使用してください．\n"
                    f"* `**単語**` のような二重アスタリスクや、行頭の `* ` は使用しないでください．\n\n"
                    f"# 参考情報 (出典: {selected_file})\n{context_text}\n\n"
                    f"# 質問\n{user_query}"
                )
                
                reply_text = await get_gemini_response(final_query)
                await client.chat_delete(channel=channel_id, ts=thinking_message['ts'])
                await send_long_message(client, channel=channel_id, thread_ts=thread_ts, text=reply_text)

            else:

                await client.chat_update(
                    channel=channel_id, ts=thinking_message['ts'], text="🤔 うーん、関連する資料は見つからなかったけど、僕の知識で答えてみるね．"
                )
                
                fallback_query = (
                    f"あなたは研究室の優秀で親しみやすいアシスタント、おくだくんです．\n"
                    f"「{user_query}」という質問を受けましたが、手元に関連する資料がありませんでした．\n"
                    f"あなたの持っている一般的な知識を最大限に活用し、後輩に教えるような親しみやすく丁寧な口調で応答してください．\n\n"
                    f"# Slack用の書式ルール\n"
                    f"* 強調したい単語は、`*単語*` のようにアスタリスクで囲んでください．\n"
                    f"* 箇条書きを使う場合は、行頭に `• ` (中黒と半角スペース) を使用してください．\n"
                    f"* `**単語**` のような二重アスタリスクや、行頭の `* ` は使用しないでください．"
                )

                reply_text = await get_gemini_response(fallback_query)

                await client.chat_update(channel=channel_id, ts=thinking_message['ts'], text=reply_text)

        except Exception as e:
            logging.error(f"メッセージ処理中のエラー: {e}")
            await client.chat_update(
                channel=channel_id, ts=thinking_message['ts'], text=f"申し訳ありません．エラーが発生しました: {e}"
            )
