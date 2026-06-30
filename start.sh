#!/bin/bash
# Download CJK font for PDF generation
mkdir -p fonts
if [ ! -f fonts/NotoSansCJKtc-Regular.otf ]; then
    curl -L -o fonts/NotoSansCJKtc-Regular.otf "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTF/TraditionalChinese/NotoSansCJKtc-Regular.otf"
fi
if [ ! -f fonts/NotoSansCJKtc-Bold.otf ]; then
    curl -L -o fonts/NotoSansCJKtc-Bold.otf "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTF/TraditionalChinese/NotoSansCJKtc-Bold.otf"
fi
echo "Fonts ready, starting server..."
exec uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}
