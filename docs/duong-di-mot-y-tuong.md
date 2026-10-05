# Đường đi của một ý tưởng — từ giả thuyết đến tiền thật

Tài liệu này mô tả **hệ thống đang có**, không phải kế hoạch. `kien-truc-v2.md`
nói *nên* xây gì và tại sao; file này nói mỗi mảnh đó hiện nằm ở đâu, và một ý
tưởng phải đi qua những cánh cửa nào trước khi được chạm vào tiền.

## Bản đồ

```
   ý tưởng (người hoặc LLM)
        |
        v
  [1] research/strategy_lab.py         sinh + kiểm định
        |  walk-forward nhiều mã, cổng thống kê ĐÃ HIỆU CHỈNH cho số phép thử
        |  → trượt: dừng ở đây (kết quả thường gặp và đúng)
        v
  [2] data/kho_luat.json               trạng thái: ung_vien
        |  người bấm: Strategy Lab → Kho luật → "Cho chạy bóng"
        v
  [3] trạng thái: bong                 chạy song song trong main.py, CHỈ ghi sổ
        |  ≥ 14 ngày VÀ đủ bằng chứng (≥20 tín hiệu đã chấm, kỳ vọng ≥ 0)
        |  người bấm "Thăng lên chủ động" + gõ câu xác nhận
        v
  [4] trạng thái: chu_dong             ĐƯỢC PHÉP chạy, nhưng vẫn CHƯA chạy
        |  người thêm tên vào ENABLED_STRATEGIES (tab Cấu hình) rồi bật lại bot
        v
  [5] ensemble thật                    allocator → LLM veto → risk engine → lệnh
```

Năm bước, và **ba trong số đó cần một con người bấm nút**. Đó là chủ ý — máy
được phép tự hạ cấp, không bao giờ được tự thăng cấp.

## Vì sao nhiều cửa như vậy

### Cửa 1 — cổng thống kê tự siết theo số phép thử

Thử 20 giả thuyết rồi chọn cái Sharpe cao nhất không phải nghiên cứu. Ngay cả
khi cả 20 ý tưởng đều vô dụng, cái "tốt nhất" trong 20 vẫn trông rất đẹp — vì
ta đang đo *cực đại của nhiễu* chứ không đo kỹ năng.

Nên ngưỡng Sharpe tăng theo số giả thuyết đã thử **luỹ kế**:

| Số phép thử luỹ kế | Sharpe đòi hỏi |
|---|---|
| 1 | 1.00 |
| 20 | 1.17 |
| 100 | 1.56 |
| 300 | 1.79 |

Bộ đếm nằm ở `data/strategy_lab_trials.json` và **chỉ tăng**. Nếu nó reset mỗi
lần chạy thì chỉ cần chạy lab 10 lần với 2 ý tưởng mỗi lần là vô hiệu hoá toàn
bộ hiệu chỉnh — mà không hề nhận ra mình đang làm vậy. File hỏng thì báo lỗi
chứ không âm thầm về 0: về 0 là nới lỏng cổng.

### Cửa 2 — LLM sinh dữ liệu, không sinh code

Kiến trúc v2 nói LLM "đề xuất giả thuyết dưới dạng code". Chạy thẳng code đó là
chạy mã tuỳ ý trên máy có `.env` chứa khoá API sàn. Một giả thuyết sai thì mất
một buổi backtest; một dòng code độc thì mất tài khoản.

Nên LLM trả về JSON theo lược đồ ở `src/strategies/rule_spec.py`, được đối chiếu
danh sách trắng cột + toán tử rồi mới biên dịch. Không `exec()`, không `eval()`.
Trần 4 điều kiện mỗi chiều: mỗi điều kiện là một bậc tự do, và luật 12 điều kiện
luôn khớp đẹp với quá khứ, không bao giờ khớp với tương lai.

### Cửa 3 — chế độ bóng không được là bóng nửa vời

Chiến lược ở trạng thái `bong` **cố ý không nằm trong** `self.strategies` của
bot. Lý do: allocator chuẩn hoá trọng số trên danh sách chiến lược, nên chỉ việc
*có mặt* trong danh sách đã làm đổi trọng số của breakout — và lúc đó chế độ bóng
không còn là bóng nữa.

Cùng nguyên tắc với `POLICY_MODE=shadow` của AI policy. Muốn không ảnh hưởng gì
thì phải *không có mặt*, chứ không phải có mặt rồi tự hứa sẽ im lặng.

Validator của web UI cũng từ chối bật một chiến lược đang ở `bong` vào
`ENABLED_STRATEGIES` — nếu không thì đó là đường vòng kết thúc chế độ bóng mà
không ai ghi lại quyết định ở đâu.

### Cửa 3b — chế độ bóng phải được CHẤM ĐIỂM, không chỉ đếm ngày

14 ngày là *thời gian phục vụ*, không phải kết quả. Kiến trúc v2 nói "nếu shadow
mode **vẫn tốt** thì mới thêm vào ensemble" — và chỉ đếm ngày thì 14 ngày im
lặng qua cổng y hệt 14 ngày tốt.

Nên mỗi ngày bot điền kết quả thật cho từng tín hiệu bóng, bằng **triple-barrier
trên dữ liệu thị trường** — giống hệt cách `continual.py` chấm AI policy, cố ý
để hai bên so sánh được với nhau. Chiến lược ở chế độ bóng không đặt lệnh nào,
nên đây là cách duy nhất; và vì barrier dùng đúng `ATR_STOP_MULT`/`ATR_TP_MULT`
mà bot thật đang dùng, con số trả lời đúng câu hỏi *"nếu vào lệnh lúc đó, với
chính cái stop và chốt lãi của bot, thì lãi bao nhiêu sau phí"*.

Cổng đòi hai điều, và cả hai đều cần:

- **≥ 20 tín hiệu đã chấm.** Kỳ vọng trên 5 lệnh là nhiễu, không phải kết quả.
- **Kỳ vọng mỗi lệnh không âm sau phí.** Không đòi đẹp — chỉ đòi đúng dấu. Đặt
  ngưỡng cao hơn ở đây sẽ lặp lại chính cái bẫy Strategy Lab đã tránh: chọn cái
  đẹp nhất trong nhiều thứ, trên một mẫu nhỏ.

Tín hiệu HOLD **cũng được ghi và chấm** (để hồ sơ không thiên lệch chọn mẫu),
nhưng không tính vào kỳ vọng mỗi lệnh — kỳ vọng chỉ có nghĩa trên những lần
chiến lược thực sự muốn vào lệnh.

Nếu chấm điểm hỏng hoặc không có dữ liệu, lớp này trả về "không chấm được" và
cổng quay về điều kiện số ngày như cũ. Một lớp **đo** không được tự biến thành
một lớp **chặn**.

### Cửa 4 — "được phép chạy" khác "đang chạy"

Lên `chu_dong` không làm chiến lược chạy. Phải thêm tên nó vào
`ENABLED_STRATEGIES`. Hai điều đó cố ý tách rời: kho luật nói *được phép*, `.env`
nói *đang chạy*, và gộp chúng làm một nghĩa là một lệnh thăng cấp cũng đồng thời
là một lệnh triển khai.

### Bất đối xứng xuyên suốt: lên thì chậm, xuống thì nhanh

Mọi cửa ở trên chỉ chặn chiều **lên**. Hạ cấp, loại bỏ, tắt — không cần điều
kiện gì, lúc nào cũng được. Lúc cần đường lui nhất là lúc mọi thứ đang hỏng, và
đó không phải lúc để bắt người ta thoả mãn điều kiện.

Máy được phép **tự hạ cấp** (`continual.theo_doi_champion` làm vậy với mô hình
ML). Máy **không bao giờ tự thăng cấp**. Một hệ thống tự nâng cấp chính nó là hệ
thống không ai chịu trách nhiệm.

## Làm ở đâu

Toàn bộ đường đi trên nằm trong bảng điều khiển, tab **Strategy Lab**:

| Bước | Trong web UI |
|---|---|
| Sinh giả thuyết bằng LLM | mục 1 · Sinh giả thuyết |
| Soạn / sửa giả thuyết tay | ô soạn JSON, có kiểm tra ngay lúc lưu |
| Chạy kiểm định | mục 2 · Kiểm định (hiện bộ đếm phép thử luỹ kế) |
| Xem kết quả | bảng "Kết quả lần chạy gần nhất" |
| Thăng / hạ cấp | mục 3 · Kho luật, nút trên từng dòng |
| Bật chiến lược đã lên `chu_dong` | tab Cấu hình → `ENABLED_STRATEGIES` |

Thăng lên **chủ động** đòi gõ đúng câu xác nhận, giống hệt nút bật bot bằng tiền
thật — đó là bước cho luật sinh lệnh trong ensemble. Hạ cấp không đòi gì.

Dòng lệnh vẫn dùng được, và tiện hơn khi muốn xem chi tiết một mục:

```bash
python run_luat.py trang-thai
python run_luat.py xem --ten <ten>
python run_luat.py thang-cap --ten <ten> --ly-do "..."
python -m research.strategy_lab trang-thai
```

**Khoá API đi một chiều.** Dán được vào tab Cấu hình, nhưng không đường nào đọc
ngược giá trị ra — không route nào trả về, không thông báo lỗi nào nhắc lại,
kể cả khi sàn từ chối. Bảng chỉ hiển thị *đã đặt hay chưa*; muốn đối chiếu thì
mở `.env` bằng trình soạn thảo.

Vì sao một chiều là đủ, mà hai chiều thì không: bảng chỉ nghe trên 127.0.0.1, và
ai vào được cổng đó thì đã bật/tắt bot và đặt lệnh được rồi — cho ghi thêm khoá
không nới rộng quyền hạn bao nhiêu. Cho *đọc* thì khác hẳn: nó biến mọi lỗ hổng
hiển thị thành một vụ lộ khoá API vĩnh viễn, và khoá đã lộ thì không rút lại
được. Đó là lý do `env_store` tách hẳn hai đường ghi: `ghi()` báo lại `cũ → mới`
cho người dùng đối chiếu, còn `ghi_bi_mat()` chỉ báo *tên* khoá đã đổi.

**Nút "Thử kết nối sàn"** gọi sàn bằng đúng giá trị đang có trong `.env` *ngay
lúc bấm*, chứ không phải bản `config` đã nạp từ lúc khởi động — vừa dán khoá
xong là thử được luôn. Nó tách làm hai bước vì hai bước hỏng vì hai lý do khác
hẳn: lấy giá hỏng là chuyện mạng hoặc tên mã, lấy số dư hỏng là chuyện khoá.
Bước riêng tư dùng `client.kiem_tra_ket_noi()` chứ không dùng `get_equity()`:
`get_equity()` nuốt mọi lỗi thành `None` để bot chạy tiếp được, nên "khoá sai"
và "tài khoản rỗng" ra cùng một kết quả — mà ở đây mã lỗi của sàn (`50111
Invalid OK-ACCESS-KEY`) chính là thứ cần thấy.

## Đổi sàn: một cú bấm, một cái bẫy

Tab Cấu hình mở đầu bằng hai thẻ **Bybit / OKX**. Bấm là đổi. Mỗi thẻ tự nói nó
cần khoá gì và đã có chưa — OKX cần thêm `OKX_API_PASSPHRASE` mà Bybit không có,
và đó là thứ người chuyển từ Bybit sang hay quên nhất. Chọn sàn không đòi phải
có khoá trước: chọn sàn và nạp khoá là hai việc, ép đúng thứ tự chỉ làm người
dùng bí.

Bốn khoá `EXCHANGE`, `BYBIT_TESTNET`, `OKX_DEMO`, `OKX_TD_MODE` **chỉ hiện ở
bảng chọn sàn**, không hiện lại ở bảng `.env` chung (`env_store.KHOA_SAN`). Cùng
một khoá vẽ ở hai chỗ thì sửa một chỗ, chỗ kia đứng im, và không ai biết chỗ nào
đang đúng.

**Cái bẫy, và chỗ bảng chặn lại.** `reconcile()` chỉ đọc vị thế từ sàn *đang cấu
hình*, nó không đối chiếu với một sổ sách riêng. Đổi sang OKX trong khi còn một
vị thế trên Bybit thì vòng sau bot thấy "không có vị thế nào" và chạy tiếp bình
thường — còn cái vị thế kia nằm lại không ai quản stop, không cả lưới `_ep_stop`.
Bot không hề báo lỗi, vì theo góc nhìn mới của nó thì không có gì sai cả.

Nên `/api/san/chon` đọc sàn đang dùng trước khi ghi, và trả 409 nếu còn vị thế
hay lệnh chờ; người dùng phải bấm thêm một nút riêng mới đi tiếp. Không có khoá
cho sàn cũ thì bỏ qua phép kiểm — không khoá thì cũng không thể có vị thế nào để
bỏ rơi. **Đọc thất bại cũng bỏ qua**, có chủ đích: chặn người dùng lại bằng một
lỗi mạng chỉ khiến họ bấm "xác nhận" theo phản xạ, làm hỏng đúng cái cảnh báo
này dựng ra để bảo vệ.

**Cache nến dùng chung giữa hai sàn**, cố ý. Tên tệp là `{mã}_{khung}.csv`,
không gắn nhãn sàn. Đo cùng thời điểm trên mainnet spot ngày 2026-09-08:
BTC lệch 0.000%, ETH 0.007%, SOL 0.010% — hai sàn được arbitrage khít, gắn nhãn
sàn chỉ tạo ra hai bản sao của cùng một dữ liệu. Đây là chuyện **khác hẳn** với
dữ liệu testnet (lệch 1.5–5%, đủ vô hiệu hoá mọi kết quả) — testnet có thanh
khoản giả, còn mainnet-sang-mainnet thì không.

**Bảng điều khiển đọc lại `.env` mỗi lần gọi** (`_CauHinhVuaDoc`), không dùng bản
`config` nạp lúc khởi động. Không có lớp này thì người dùng bấm đổi sàn xong,
nhãn trên đầu trang vẫn ghi sàn cũ — họ đã lưu đúng, chỉ là bảng không biết. Lớp
này ép kiểu theo đúng kiểu mà `config.py` dùng cho từng khoá, chứ không theo một
bảng liệt kê: bảng liệt kê sẽ lạc hậu ngay lần đầu ai đó thêm khoá mới, mà kiểu
hỏng ở đây không báo lỗi — `len(SYMBOLS)` trên một chuỗi vẫn chạy, chỉ là trả về
số ký tự thay vì số mã.

## Lớp thứ hai: bộ lọc meta-label

Đường đi ở trên sinh ra *tín hiệu*. Lớp này quyết định **có nghe tín hiệu đó
không** — và nó là lớp học máy duy nhất hiện đang đứng gần được việc.

### Vì sao nó tồn tại, khi đã có AI policy

AI policy (`src/policy.py`) hỏi một câu quá khó: *trong mọi cây nến của mọi mã,
cái nào đáng mua?* Trên dữ liệu mainnet 4H, 12 mã, 4.5 năm:

| | Tỷ lệ lãi sau phí |
|---|---|
| Mọi nến | 39.53% |
| Nến mà breakout đã phát tín hiệu | **42.86%** |

Tỷ lệ cơ sở của câu hỏi thứ nhất nằm **dưới** hàng rào chi phí, nên mô hình phải
tự sinh ra toàn bộ lợi thế. Nó không làm được: dự đoán tự tin nhất đạt 0.4195
trong khi hoà vốn đòi 0.432, nên trên 15.096 nến kiểm định nó vào đúng **0 lệnh**.

Chỉ việc *đứng yên cho tới khi một chiến lược luật lên tiếng* đã kéo tỷ lệ cơ sở
lên 3.3 điểm phần trăm. Bài toán còn lại nhỏ hơn hẳn.

### Hoà vốn thực là 43.5%, không phải 40%

Công thức barrier nói TP 3×ATR / SL 2×ATR nên chỉ cần thắng 40% là hoà. Nhưng
nhiều lệnh hết hạn giữa chừng, không chạm barrier nào — biên độ **thực** đo được
là thắng +6.95% / thua −5.35%, tỷ lệ 1.30 chứ không phải 1.50:

```
p = |thua| / (thắng + |thua|) = 0.0535 / (0.0695 + 0.0535) = 0.4350
```

Mọi chỗ tính hoà vốn trong code đều dùng biên độ thực (`meta_label.bien_do_thuc`).
Dùng tỷ lệ danh nghĩa sẽ cho một ngưỡng dễ hơn thực tế, và bộ lọc sẽ để lọt đúng
những tín hiệu vừa đủ xấu để làm mất tiền.

### Mốc so sánh không phải AUC 0.5

Đây là khác biệt quan trọng nhất giữa lớp này và AI policy. Bên kia hỏi "mô hình
có kỹ năng không", mốc là ngẫu nhiên. Bên này hỏi "bộ lọc có làm ra tiền hơn việc
**không lọc gì** không", và mốc là chính chiến lược luật đang chạy.

Nên mọi chỉ số trong cổng đều đọc theo cặp: `ky_vong` đi kèm `ky_vong_khong_loc`,
`profit_factor` đi kèm `profit_factor_khong_loc`. Một bộ lọc AUC 0.60 mà sau khi
lọc vẫn lỗ hơn breakout thô thì tệ hơn vô dụng — nó làm ta tưởng mình đang được
bảo vệ.

### Hai cái bẫy đã sập khi xây lớp này

**Khối hiệu chuẩn liền mạch = một chế độ thị trường.** Lần chạy đầu rơi trúng
đoạn 83 ngày breakout thắng **21%** thay vì 43% trung bình. Không ngưỡng nào lãi
được ở đó — mà cả ngưỡng, số vòng boosting lẫn biên độ thắng/thua đều rút ra từ
chính đoạn đó. Với mật độ tín hiệu ~4% số nến, một khối 500 nến chỉ chứa ~370 tín
hiệu và cả 370 cái đến từ một đoạn liên tục. Sửa bằng purged K-fold trên toàn vùng
train (`meta_train.du_doan_ngoai_mau`): 7.075 dự đoán ngoài mẫu trải khắp mọi chế
độ. Bẫy này **không** xuất hiện ở AI policy vì bên đó có 215k dòng.

**Bộ chọn ngưỡng và cổng bất đồng về vùng khả thi.** Bộ chọn được tự do chọn
ngưỡng giữ 3.7% trong khi cổng đòi 15–90%: lần nào cũng sinh ra một bộ lọc mà cổng
chắc chắn từ chối, và không ai đọc ra được rằng hai lớp đang cãi nhau.
`chon_nguong()` giờ nhận đúng `GATE_META_TY_LE_GIU_*` mà cổng dùng.

### Ngưỡng tối đa hoá TỔNG lợi nhuận, không phải kỳ vọng mỗi lệnh

Hai mục tiêu này kéo về hai hướng ngược nhau. Giữ 5% tín hiệu với kỳ vọng 1.78%
nghe đẹp hơn giữ 40% với kỳ vọng 0.40%, nhưng trên 1.000 cơ hội thì cái đầu làm ra
0.089% còn cái sau 0.160% — gần gấp đôi. Tối đa hoá kỳ vọng mỗi lệnh luôn đẩy
ngưỡng lên cao nhất có thể, tức luôn chọn vài lệnh may nhất: một dạng overfit đội
lốt kỷ luật.

### Trạng thái tính đến 2026-09-10: chưa đủ ổn định

Trên cửa sổ gần nhất bộ lọc trông tốt — kỳ vọng +0.0094 so với +0.0012 không lọc,
PF 1.43 so với 1.04, đối chứng nhãn xáo trộn sạch (0.523). Nhưng
`python run_meta.py quet` trên 6 cửa sổ × 3 seed:

```
AUC theo cửa sổ:  0.584 / 0.484 / 0.585 / 0.500 / 0.580 / 0.487
Cải thiện dương:  11/18 lần chạy
```

AUC nhảy giữa ~0.58 và ~0.49 — ba cửa sổ có kỹ năng thật, ba cửa sổ tệ hơn ngẫu
nhiên. Cửa sổ cho +0.0414 chỉ giữ 1.7% tín hiệu, tức vài lệnh may. **Cổng từ chối,
và đó là kết quả đúng.** Một bộ lọc không biết gì vẫn đang chặn lệnh thật.

Trộn cả ba chiến lược vào làm nguồn thì hỏng hẳn (PF 0.66): trend_following và
mean_reversion có biên độ âm, trộn vào là làm bẩn mẫu.

### Vị trí trong đường ống, và ba câu trả lời

```
chiến lược luật → ensemble → [BỘ LỌC META] → LLM veto → risk engine → lệnh
```

| Trả lời | Hệ số | Khi nào |
|---|---|---|
| GIỮ | 1.0 | p ≥ ngưỡng |
| GIẢM | `POLICY_FILTER_GIAM` | p dưới ngưỡng nhưng trong `META_VUNG_GIAM` |
| CHẶN | 0.0 | p dưới hẳn |
| **không ý kiến** | 1.0 | thiếu đặc trưng, sai dấu vân tay, quá ít mã |

**Mặc định khi không chắc là CHO QUA**, khác `MLPolicy` mặc định là HOLD. Ở đây ta
đang xen vào một tín hiệu đã qua kiểm định của chiến lược luật; chặn nó vì một lý
do kỹ thuật là thay một quyết định có cơ sở bằng một quyết định không có cơ sở nào.

Bộ lọc cũng **không chấm điểm tín hiệu của chiến lược nó chưa học**
(`chien_luoc_nguon` trong meta) — chấm một phân bố nó chưa từng thấy là đoán mò.

### Làm ở đâu

Tab **Bộ lọc** trong bảng điều khiển, hoặc dòng lệnh:

```bash
python run_meta.py quet     # chạy CÁI NÀY trước khi tin bất kỳ kết quả nào
python run_meta.py hoc
python run_meta.py trang-thai
```

`quet` chạy lại trên nhiều cửa sổ và nhiều seed. Một lần `hoc` chấm điểm trên một
cửa sổ duy nhất, tức một chế độ thị trường duy nhất — và ta đã thấy điều đó nguy
hiểm đến mức nào.

## Hai lớp bảo vệ chạy nền, không liên quan tới đường đi trên

**Lưới an toàn stop** (`position_manager._ep_stop`). Lệnh gửi lên sàn có kèm
stop-loss, nhưng cái stop đó có thể *không tồn tại* mà bot vẫn tưởng là có:
sai tên tham số, lệnh algo bị từ chối, hoặc lỗi phía sàn. Bybit gắn SL thẳng vào
lệnh; OKX quản lý SL bằng lệnh algo riêng và tham số gắn kèm có thể đổi theo
phiên bản API. Nếu tên trường sai, sàn vẫn khớp **lệnh chính** và âm thầm bỏ qua
phần SL — kết quả là một vị thế không có bảo vệ, trong khi log của bot ghi rõ
ràng nó có stop ở 95.

Nên mỗi vòng, bot tự đọc giá thật: nếu giá đã xuyên qua stop mà vị thế **vẫn còn
trên sàn**, bot tự đóng bằng lệnh thị trường. Lớp này không dùng API đặc thù của
sàn nào — chỉ dùng `get_klines` và `place_order`, hai đường đã chạy hằng ngày.
Tắt bằng `EP_STOP_PHIA_BOT=false`, nhưng không nên.

**Kênh điều khiển UI → bot** (bảng `lenh_dieu_khien`). Circuit breaker nằm trong
bộ nhớ tiến trình bot, web không sửa trực tiếp được. Nút "Reset circuit breaker"
xếp một lệnh vào DB; bot đọc ở đầu vòng kế tiếp. Ba ràng buộc:

- **Danh sách trắng hai lớp.** Web có một danh sách, bot có một danh sách riêng
  (`main.TradingBot.LENH_CHO_PHEP`) và lớp của bot mới là cái quyết định. Web có
  thể bị sửa; bot thì tự bảo vệ mình. Có test khoá hai danh sách phải khớp nhau.
- **Lệnh hết hạn sau 10 phút.** Bot tắt ba ngày rồi bật lại không nên thi hành
  một lệnh xếp từ ba ngày trước — lúc đó bối cảnh đã khác, và một "reset breaker"
  từ quá khứ sẽ âm thầm xoá một cảnh báo đang còn đúng.
- **Không có lệnh nào đóng vị thế hay đổi cấu hình.** Đóng vị thế là việc của
  chiến lược và risk engine; đổi cấu hình thì phải khởi động lại bot một cách
  có ý thức.

## Điều tài liệu này không hứa

Không cửa nào ở trên tạo ra lợi thế. Chúng chỉ ngăn việc **nhầm nhiễu với lợi
thế**, và ngăn một ý tưởng chưa được kiểm chứng đi tắt tới chỗ có tiền.

Tính đến 2026-09, chưa chiến lược nào — kể cả breakout 4H đang chạy testnet —
vượt được cổng thống kê. Kết quả đúng của hầu hết các lần chạy lab là "không ý
tưởng nào qua cổng". Đó là hệ thống đang làm việc.
