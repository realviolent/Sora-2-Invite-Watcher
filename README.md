# Sora2 Invite Code Watcher

Qiitaのコメントから6桁コードを監視し、見つけ次第ビープ＆通知＆クリップボード（任意で前面アプリに ⌘V→Enter）を行うツール。

## Quickstart
```bash
pip install -r requirements.txt  # (requests, playwright など)
python -m playwright install chromium  # fallbackを使う場合
export QIITA_TOKEN=...           # read_qiita スコープのPAT
export POLL_SECONDS=2
export AUTO_PASTE=1              # 前面アプリに ⌘V→Enterを送る
python sora_lastcode_watch.py
> もし `requirements.txt` がまだ無ければ作っておきます（最低限）：
```bash
cat > requirements.txt <<'EOF'
requests>=2.32.0
playwright>=1.55.0
