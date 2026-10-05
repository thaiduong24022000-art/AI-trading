# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Dự án

AI Trade Bot v2 cho Bybit (và OKX) — bot giao dịch định lượng cá nhân, **hiện chưa chạy tiền thật**
(mặc định `.env`: `DRY_RUN=true`, testnet/demo=true, `POLICY_MODE=off`). Toàn bộ code, docstring, log
message và tài liệu trong repo viết bằng tiếng Việt — chuỗi log/console cố ý **không dấu** để tránh lỗi
encoding trên console Windows (xem đầu `config.py`). Giữ nguyên quy ước đó khi sửa code: docstring/tài
liệu có dấu, chuỗi in ra console thì không dấu.

`docs/kien-truc-v2.md` là **nguồn sự thật về ý định kiến trúc** — do người dùng tự viết tay, không phải
sinh tự động. Khi code và tài liệu này lệch nhau, đó là một phát hiện đáng báo cáo, không phải chuyện
nhỏ nên tự sửa cho khớp. `docs/vong-hoc-lien-tuc.md` giải thích chi tiết vòng học AI policy (mục tương
ứng bên dưới). Gần như mọi module trong `src/` đều có docstring đầu file giải thích **vì sao** nó tồn
tại và bẫy nào nó đang chặn — đọc docstring trước khi sửa, đừng chỉ đọc code.

## Lệnh thường dùng

### Môi trường Python

Trên máy này lệnh `python` trơ trọi trỏ tới stub Microsoft Store và không chạy được. Luôn gọi qua venv
của dự án:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

venv đã có sẵn `pandas`, `numpy`, `lightgbm`, `scikit-learn`, `flask`, `pytest`. Nếu thiếu `pybit`/
`anthropic`, `main.py` sẽ dừng ở bước kết nối sàn nhưng backtest và toàn bộ test suite vẫn chạy được —
`bybit_client`/`okx_client` bắt `ImportError` có chủ đích ở đường đó.

### Test

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q                                # toàn bộ (~500 test)
.\.venv\Scripts\python.exe -m pytest tests/test_risk_manager.py -q            # một file
.\.venv\Scripts\python.exe -m pytest tests/test_risk_manager.py::test_ten -q  # một test
```

Quy ước bắt buộc (`tests/conftest.py`): **test không được phụ thuộc giá trị `.env` của máy đang chạy.**
Cần config riêng thì dùng fixture `make_cfg(**overrides)` để tạo bản sao `config` có thể sửa tự do,
không import/sửa `config` thật.

### Chạy bot / web UI

```powershell
python main.py                 # vòng lặp liên tục
python main.py --once          # một vòng rồi thoát - dùng để test tay
python run_webui.py            # bảng điều khiển http://127.0.0.1:5000 (CHỈ nghe 127.0.0.1, cố ý)
```

### Backtest & kiểm định

```powershell
python run_backtest.py backtest --synthetic --strategy all --report   # backtest 1 lần, sinh bao_cao_backtest.html
python run_backtest.py download --symbol BTCUSDT --bars 8000          # tải lịch sử về data/cache/
python run_backtest.py walkforward --strategy all                     # walk-forward + cổng thống kê (kết quả đáng tin)
python run_phase0.py --symbols BTCUSDT,ETHUSDT --timeframes 60,240,D  # strategy validation nhiều khung/mã
```

Dữ liệu lịch sử **luôn** tải từ mainnet (`config.DATA_TESTNET`), tách rời khỏi nơi đặt lệnh
(`BYBIT_TESTNET`/`OKX_DEMO`) — giá testnet lệch giá thật 1.5-5%, đủ lớn để mọi kết quả backtest trên đó
vô nghĩa.

### Vòng học AI policy / bộ lọc meta-label / kho chiến lược luật

```powershell
python run_policy.py hoc            # huấn luyện challenger + chấm cổng thăng cấp
python run_policy.py trang-thai     # champion hiện tại, lịch sử phiên bản, kết quả thật
python run_policy.py theo-doi       # điền kết quả thật + kiểm tra hạ cấp (đã tự chạy hằng ngày trong main.py)

python run_meta.py hoc              # huấn luyện bộ lọc meta-label
python run_meta.py quet             # BẮT BUỘC trước khi tin bất kỳ kết quả "hoc" nào - quét ổn định nhiều cửa sổ x seed

python run_luat.py trang-thai       # kho chiến lược luật: ung_vien / bong / chu_dong / da_loai
```

### Nghiên cứu / thu thập dữ liệu

```powershell
python -m research.ic_study --symbols <...> --interval 240 --target edge --stride 60   # đo Information Coefficient
python -m research.strategy_lab trang-thai                                              # Strategy Lab (Nâng cấp 5)
python -m research.collect_orderbook --symbols BTCUSDT,... --depth 50 --category linear # thu thập sổ lệnh
```

Thu thập sổ lệnh cần chạy liên tục nhiều tháng (nguồn dữ liệu duy nhất không tải lại được sau này) —
dùng `thu_thap_so_lenh.bat`, hoặc bền hơn qua Windows Task Scheduler (lệnh mẫu trong
`bat_thu_thap_so_lenh.xml.txt`). Tiến trình khởi động qua `.bat` hay qua shell của Claude Code đều
**không** sống qua việc đóng cửa sổ/khởi động lại máy — chỉ Task Scheduler mới bền.

## Kiến trúc

### Đường ống quyết định (`main.py`)

```
dữ liệu -> chỉ báo -> regime -> ensemble chiến lược (+ AI policy) -> allocator
   -> AI policy filter -> bộ lọc meta-label -> exit-on-reverse -> LLM veto
   -> risk engine -> thực thi -> ghi log
```

Mỗi bước là một module riêng, gọi tuần tự trong `TradingBot.process_symbol()`: `src/indicators.py` →
`src/regime.py` → `src/strategies/*` + `src/allocator.py` (`combine_signals`) → `src/policy.py`/
`src/meta_policy.py` → `src/sentiment.py` (LLM veto) → `src/risk_manager.py` → `src/executor.py` →
`src/storage.py`.

**Ràng buộc kiến trúc quan trọng nhất, lặp lại ở nhiều lớp độc lập:** mọi lớp nằm *sau* khi tín hiệu đã
sinh ra (AI policy ở chế độ `filter`, bộ lọc meta-label, LLM veto) chỉ được **CHẶN hoặc GIẢM quy mô**,
không bao giờ được tự tạo lệnh hay làm tín hiệu mạnh lên. Risk engine luôn là cổng kiểm duyệt cuối
cùng, không lớp nào được đi tắt qua nó.

Hệ quả trực tiếp, dễ bẫy người sửa code sau: **chiến lược luật ở trạng thái `bong` (shadow) và AI
policy ở chế độ `shadow`/`filter` cố ý KHÔNG nằm trong `self.strategies`.** `allocator.allocate()`
chuẩn hoá trọng số trên *danh sách* chiến lược; chỉ cần có mặt trong danh sách — dù không bao giờ phát
tín hiệu — là đã kéo trọng số của các chiến lược khác xuống, tức chế độ "bóng" không còn là bóng nữa.
Bất biến này bị khoá bằng `tests/test_main_policy.py`. Xem `main.py:_tao_policy()` và
`docs/vong-hoc-lien-tuc.md` §5.

### Nguyên tắc "lên chậm, xuống nhanh, người mới được cho lên"

Lặp lại giống hệt nhau ở ba nơi độc lập trong repo — nhận ra pattern chung này thì đọc
`src/model_store.py`, `src/strategies/kho_luat.py`, `src/continual.py` nhanh hơn nhiều:

| | Máy được tự làm | Chỉ người mới được làm |
|---|---|---|
| Model AI policy/meta (`model_store.py`) | Hạ champion (`continual.py`, tự động hằng ngày) | Thăng cấp challenger lên champion (`thang_cap()`) |
| Chiến lược luật (`kho_luat.py`) | — | Lên bậc `ung_vien→bong→chu_dong`, không nhảy cóc |
| Chế độ triển khai (`POLICY_MODE`) | — | Đổi `off/shadow/filter/active` (sửa `.env` + khởi động lại) |

Một chiến lược lên `chu_dong` trong kho luật **vẫn chưa chạy** cho tới khi tên nó được thêm vào
`ENABLED_STRATEGIES` trong `.env` và bot khởi động lại — cố ý tách thành ba bước độc lập (qua cổng,
được phép chạy, đang chạy thật).

### Hai sàn: Bybit/OKX qua một factory

`src/exchange.py:build_client(cfg)` là **nơi duy nhất** chọn `BybitClient` hay `OkxClient` theo
`config.EXCHANGE`. `main.py`, `run_backtest.py` và các script tải dữ liệu đều gọi qua đây, không import
thẳng client cụ thể — đổi sàn chỉ cần sửa `.env`. OKX cần thêm `OKX_API_PASSPHRASE` mà Bybit không có
(lỗi hay gặp nhất khi chuyển từ Bybit sang OKX).

### `config.py` — nguồn cấu hình trung tâm

Đọc từ `.env` qua `python-dotenv`, mặc định mọi thứ ở chế độ an toàn (testnet, `DRY_RUN=true`, LLM
tắt). Mọi hằng số cổng thống kê (`GATE_*`), risk (`RISK_PER_TRADE`, `MAX_PORTFOLIO_HEAT`...) và chế độ
(`POLICY_MODE`, `ENABLED_STRATEGIES`...) đều nằm ở đây kèm chú thích lý do ngay cạnh — đọc file này
trước khi đổi tham số của bất kỳ module nào. `ENABLED_STRATEGIES` mặc định chỉ có `breakout`: kiểm định
trên dữ liệu mainnet 4.5 năm cho thấy `trend_following`/`mean_reversion` có biên độ âm.

Web UI sửa `.env` qua `webui/env_store.py`, có **hai đường ghi tách biệt**:
- `CO_THE_SUA`: khoá cấu hình thường, đọc/ghi hai chiều, mỗi khoá có validator riêng.
- `KHOA_BI_MAT` (API key/secret/token): chỉ **ghi**, không có đường nào đọc giá trị thật ra HTTP — UI
  chỉ biết "đã đặt hay chưa". Thêm khoá bí mật mới thì thêm vào `KHOA_BI_MAT`, **không bao giờ** vào
  `CO_THE_SUA`.

`DOI_BAI_TOAN = (ATR_STOP_MULT, ATR_TP_MULT, KLINE_INTERVAL)`: đổi các khoá này đổi luôn "bài toán" mà
model AI policy đã học (dấu vân tay mô hình băm theo các giá trị này) — UI cảnh báo trước khi ghi.

### Vòng học liên tục — AI policy (`src/policy.py`, `policy_train.py`, `model_store.py`, `continual.py`, `validation.py`)

Hai câu hỏi tách rời, đừng trộn khi sửa code (xem `docs/vong-hoc-lien-tuc.md`): **học được gì không, số
đo có thật không** (`validation.py` + `policy_train.py` + cổng thăng cấp) khác với **học xong triển
khai an toàn thế nào** (`model_store.py` + `policy.py` + 4 chế độ + đường hạ cấp).

4 chế độ triển khai (`POLICY_MODE`; hằng số trong `src/policy.py`: `TAT=off, BONG=shadow, LOC=filter,
CHU_DONG=active`):

| Chế độ | Trong `ensemble`? | Được làm gì |
|---|---|---|
| `off` | không | không nạp model |
| `shadow` | không | dự đoán + ghi sổ, tín hiệu luôn bị nén về HOLD |
| `filter` | không | chỉ chặn/giảm quy mô tín hiệu của chiến lược luật |
| `active` | có | thành viên bình thường của ensemble |

Chống rò rỉ khi huấn luyện — bốn lớp, mỗi lớp từng gây sai số thật trong dự án này nên đừng bỏ khi
refactor:
1. **Purge** — bỏ mẫu có nhãn triple-barrier kéo dài sang vùng test.
2. **Embargo** — khoảng trống thêm `max_horizon` nến giữa train/test.
3. **Trọng số duy nhất** (Lopez de Prado) chuẩn hoá về trung bình 1.0 trước khi đưa vào LightGBM — bỏ
   qua bước này thì `lambda_l2`/`min_sum_hessian_in_leaf` (ngưỡng tuyệt đối) phạt mô hình sai ~60 lần
   ngoài ý muốn, và triệu chứng rất dễ đọc nhầm thành "dữ liệu không có tín hiệu".
4. **t-stat hiệu chỉnh Newey-West** — t thô có thể phóng đại ~2.7 lần vì các mốc thời gian cạnh nhau
   không độc lập (nhãn chồng lấn tới 60 nến).

Luôn kèm **đối chứng nhãn xáo trộn** chạy song song toàn bộ pipeline — nếu đối chứng cũng đạt điểm cao
thì rò rỉ nằm trong pipeline và mọi số liệu khác đều là rác; vòng học phải dừng và báo động thay vì
thăng cấp (`tests/test_continual.py::test_ban_dac_trung_ro_ri_vao_thi_vong_hoc_phai_bat_duoc` khoá điều
này).

Không bao giờ huấn luyện trên **kết quả lệnh thật đã vào** — đó là thiên lệch chọn mẫu tự khuếch đại
qua mỗi vòng. Nhãn huấn luyện luôn là triple-barrier tính cho mọi cây nến, kể cả những lần policy nói
HOLD; kết quả lệnh thật chỉ dùng để theo dõi và hạ cấp.

### Bộ lọc meta-label (`src/meta_label.py`, `meta_train.py`, `meta_continual.py`, `meta_policy.py`, kho riêng `models_meta/`)

Câu hỏi khác hẳn AI policy: AI policy hỏi "nến này có đáng mua không" (khó — tỷ lệ cơ sở nằm dưới hoà
vốn); meta-label chỉ hỏi "tín hiệu mà một chiến lược **luật** vừa phát ra có đáng nghe không" (dễ hơn
nhiều vì đã có chiến lược nguồn chọn lọc trước — tỷ lệ cơ sở cao hơn hẳn). Chỉ chấm điểm tín hiệu của
chiến lược nằm trong `META_CHIEN_LUOC` (mặc định `breakout`); tín hiệu từ chiến lược khác đi tiếp
nguyên vẹn, không qua bộ lọc. Mặc định khi không chắc là **cho qua**, ngược với `MLPolicy` (mặc định
HOLD) — vì ở đây đang xen vào một tín hiệu đã qua kiểm định riêng của chính nó, chặn nhầm là lấy quyết
định có cơ sở thay bằng quyết định không cơ sở.

Kết quả đo được dao động thật giữa các cửa sổ walk-forward (AUC quan sát được nhảy giữa ~0.58 và ~0.49)
— **luôn chạy `run_meta.py quet` trước khi tin một lần `hoc`**; một cửa sổ kiểm định là một chế độ thị
trường, không phải một kết luận.

### Backtest trung thực (`backtest/engine.py`, `metrics.py`, `walkforward.py`, `report.py`)

Bốn quy tắc cứng trong engine: không lookahead (tín hiệu tại nến i, khớp tại giá mở cửa nến i+1), có
phí + slippage cả hai chiều, stop/TP trong cùng một nến kiểm tra theo giả định **bi quan** (chạm cả hai
thì coi là chạm stop trước), sizing dùng đúng `RiskManager` của bot live chứ không all-in mỗi lệnh. Một
chiến lược chỉ đáng tin sau khi qua `walkforward.py` (tối ưu trên train, đo trên test ngoài mẫu, trượt
cửa sổ) và vượt toàn bộ `GATE_*` trong `config.py` (Sharpe, profit factor, max drawdown, số lệnh tối
thiểu, độ suy giảm in-sample → out-of-sample).

### Lưu trữ & vận hành

`src/storage.py` (SQLite, `data/trading.db`) ghi kèm **lý do** cho mọi quyết định, kể cả lúc HOLD — để
trả lời được "vì sao bot vào/không vào lệnh này" nhiều tháng sau, và để hồ sơ kết quả trực tuyến của
policy không bị thiên lệch về phía những quyết định đã được chọn. `src/reconciliation.py` đối soát vị
thế với sàn (nguồn sự thật) mỗi lần khởi động — lệch thì dừng lại báo người, không đoán và tự "sửa".
`src/position_manager.py` là lớp nối vòng đời vị thế giữa backtest và bot live (mở/đóng/ghi kết quả) —
thiếu lớp này thì portfolio heat chỉ tăng không bao giờ giảm, và circuit breaker dựa trên chuỗi thua
liên tiếp là code chết.

`webui/app.py` (~1500 dòng) là control panel Flask, các route API tương ứng gần như 1-1 với các CLI ở
trên (`/api/policy*`, `/api/meta*`, `/api/kho_luat*`, `/api/gia_thuyet*`...). Chỉ nghe `127.0.0.1` — cố
ý, vì bảng điều khiển có quyền bật/tắt bot và gián tiếp đặt lệnh thật. Flask chạy `debug=False` (bật
debug là mở một console chạy code tuỳ ý trên cổng mạng) nhưng có bật `TEMPLATES_AUTO_RELOAD` thủ công,
nên sửa `webui/templates/` không cần khởi động lại server. Mọi dòng trạng thái trên UI phải trả lời
"cái này có **chạy được** không", không phải "có được cấu hình không" — hai câu khác nhau (một API key
có thể "đã đặt" mà vẫn bị sàn từ chối).

## Bẫy hay gặp khi sửa code ở đây

- **`&&` trong lệnh Bash nhiều bước có thể đứt giữa chừng** nếu một bước trả về exit code khác 0 dù
  không phải lỗi thật (ví dụ `grep -c` không khớp) — các bước sau âm thầm không chạy nhưng output vẫn
  trông như đã chạy đủ. Kiểm từng bước riêng khi có bước nào đó có thể "thất bại" theo exit code.
- **Trùng `id` trong `webui/templates/index.html`**: `querySelector` chỉ thấy phần tử đầu tiên, nên tab
  console của tính năng cũ sẽ âm thầm ngừng nhận log khi tab mới dùng trùng id. Grep id hiện có trước
  khi đặt tên cho tab mới.
- **pandas 3.x**: `DatetimeIndex.astype("int64")` trả về **giây**, không phải nano-giây như pandas 2.
  Muốn mili-giây phải ép rõ: `ts.astype("datetime64[ms]").astype("int64")`.
- File JSON có key trùng nhau hoặc định dạng đặc biệt (thụt lề, có/không newline cuối) tuyệt đối không
  nên đọc bằng `json.load` rồi `json.dump` lại nguyên file — round-trip qua parser âm thầm làm mất bản
  ghi trùng và đổi định dạng thành diff rác. Chèn bằng thao tác văn bản (tìm anchor, nối chuỗi) rồi
  validate lại bằng `json.loads`/so khớp từng khối với bản cũ.
