# Vòng học liên tục — AI policy

Tài liệu này giải thích **tại sao** hệ thống được dựng như vậy. Các ràng buộc bên
dưới chỉ giữ được nếu người sửa code sau hiểu chúng tồn tại để chặn cái gì —
mọi ràng buộc chống rò rỉ đều trông như thủ tục thừa cho đến ngày nó cứu bạn.

---

## 1. Hai câu hỏi tách rời

Yêu cầu ban đầu là "AI học từ dữ liệu và từ kết quả các quyết định trước để chọn
LONG / SHORT / HOLD tốt hơn, nhưng không leakage và không tự phá model đang chạy".
Đó là **hai** bài toán, và trộn chúng lại là nguồn gốc của hầu hết các hệ thống
kiểu này thất bại:

| Câu hỏi | Giải bằng |
|---|---|
| Học được gì không, và số đo có thật không? | `validation.py` + `policy_train.py` + cổng thăng cấp |
| Học xong rồi thì triển khai thế nào cho an toàn? | `model_store.py` + `policy.py` + 4 chế độ + đường hạ cấp |

---

## 2. Đường đi của một mô hình

```
   dữ liệu thị trường (cache mainnet)
            |
       xây panel + gán nhãn triple-barrier          features.py, labeling.py
            |
   cắt train | embargo | calib | embargo | val      validation.cat_ba_khoi
            |
       LightGBM: 2 mô hình nhị phân                 policy_train.huan_luyen
       + đối chứng nhãn xáo trộn
            |
        CỔNG THĂNG CẤP  ────── trượt ──> lưu phiên bản, GIỮ NGUYÊN champion
            | đạt
       champion mới (bất biến, có thẻ mô hình)      model_store.thang_cap
            |
     chạy ở chế độ SHADOW nhiều tuần                POLICY_MODE=shadow
            |
       ghi mọi dự đoán + kết quả thật               policy_predictions
            |
    kết quả thật khớp kiểm định? ── không ──> HẠ CẤP tự động
            | có
       người quyết định nâng lên filter → active
```

Điểm cần nhớ: **huấn luyện xong không có nghĩa là được triển khai**, và
**được triển khai không có nghĩa là được đụng vào lệnh thật.**

---

## 3. Chống rò rỉ — bốn lớp

### 3.1 Purge

Nhãn triple-barrier mất tới 60 nến mới ngã ngũ. Một mẫu ở cuối vùng train có nhãn
kéo dài sang vùng test thì nó "biết" một phần tương lai của test. Điều kiện giữ
lại: `vị_trí + bars_held < test_lo`.

### 3.2 Embargo

Sau purge vẫn còn tự tương quan. Bỏ thêm một khoảng trống bằng `max_horizon` nến
giữa hai vùng.

### 3.3 Trọng số duy nhất

Hai mẫu cạnh nhau với `max_horizon=60` trùng nhau 98% khoảng thời gian — chúng gần
như là **cùng một quan sát được đếm 60 lần**. Trọng số duy nhất
(Lopez de Prado) hạ trọng số các mẫu trùng lặp.

> Chi tiết dễ sai: trọng số duy nhất có giá trị quanh `1/60`. Đưa thẳng vào LightGBM
> thì tổng hessian nhỏ đi ~60 lần, mà `lambda_l2` và `min_sum_hessian_in_leaf` là
> ngưỡng **tuyệt đối** trên đại lượng đó — mô hình bị phạt nặng gấp 60 lần ngoài ý
> muốn và ngừng học sau vài vòng boosting. Triệu chứng đó rất dễ đọc nhầm thành
> "dữ liệu không có tín hiệu". Vì vậy `chuan_hoa_trong_so()` đưa trung bình trọng
> số về 1.0 trước khi huấn luyện, giữ nguyên tỷ lệ giữa các mẫu.

### 3.4 t-stat hiệu chỉnh tự tương quan (Newey–West)

IC được đo tại **từng mốc thời gian** rồi lấy t-stat trên chuỗi IC — vì 22 mã tại
cùng một mốc không phải 22 quan sát độc lập. Nhưng các **mốc** cạnh nhau cũng không
độc lập, vì nhãn của chúng chồng lấn nhau tới 60 nến.

Con số cụ thể từ lần chạy thật đầu tiên trên dữ liệu mainnet 4H, 22 mã:

```
t-stat thô (giả định độc lập) : 7.15    <- sai, và trông rất thuyết phục
t-stat Newey-West (lag=60)    : 2.61    <- con số thật
```

**Chênh lệch ~2.7 lần chính là mức độ một báo cáo ngây thơ sẽ nói dối.** Đây đúng
là cái bẫy đã làm hỏng nghiên cứu decile spread trước đó của dự án. Cổng thăng cấp
chỉ dùng bản đã hiệu chỉnh; bản thô vẫn được in ra cạnh nó để chênh lệch luôn hiện
ra trước mắt người đọc.

### 3.5 Đối chứng nhãn xáo trộn

Toàn bộ quy trình chạy lại lần hai trên **nhãn đã xáo trộn**. Cùng số dòng, cùng
phân bố đặc trưng, cùng phép chia, cùng trọng số — chỉ liên kết đặc trưng↔nhãn bị
phá. Kết quả **phải** vô dụng. Nếu nó cũng đẹp thì rò rỉ nằm trong đường ống và mọi
số liệu khác đều là rác; vòng học dừng lại và báo động thay vì thăng cấp.

*Một bộ kiểm tra không thể thất bại thì không chứng minh được gì.*
`tests/test_continual.py::test_ban_dac_trung_ro_ri_vao_thi_vong_hoc_phai_bat_duoc`
cắm thẳng một cột bằng kết quả tương lai vào bộ đặc trưng và bắt hệ thống phải kêu.

---

## 4. Không tự phá model đang chạy — năm cơ chế

| Cơ chế | Chặn điều gì |
|---|---|
| **Bất biến** — phiên bản đã ghi không bao giờ bị sửa | số liệu trên thẻ mô hình "trôi" khỏi mô hình sinh ra nó |
| **Thăng cấp là hành động riêng** — `luu()` không triển khai | một cửa sổ dữ liệu bất thường đẩy thẳng mô hình xấu lên chạy |
| **Dấu vân tay** — băm của `[cột đặc trưng] + ATR_STOP_MULT + ATR_TP_MULT + phí + slippage` | ai đó đổi `ATR_STOP_MULT` từ 2.0 xuống 1.5; mô hình cũ vẫn nạp được, vẫn dự đoán bình thường, nhưng đang trả lời **một câu hỏi khác** |
| **Phải hơn champion một biên** (AUC + 0.005) | đổi mô hình liên tục vì nhiễu, mỗi lần đổi là mất hồ sơ kết quả trực tuyến đang tích lũy |
| **Hạ cấp tự động** | mô hình xuống cấp lúc không ai nhìn màn hình |

Hạ cấp lùi về phiên bản trước, hoặc về **không có mô hình nào** — lúc đó bot vẫn
chạy bình thường bằng chiến lược luật. Đó là lý do policy luôn là lớp **thêm vào**,
không phải lớp thay thế.

---

## 5. Bốn chế độ triển khai

| Chế độ | Nằm trong ensemble? | Được làm gì |
|---|---|---|
| `off` | không | không nạp mô hình |
| `shadow` | **không** | dự đoán + ghi sổ, tín hiệu luôn bị nén về HOLD |
| `filter` | **không** | chỉ được **chặn** hoặc **giảm** quy mô tín hiệu của chiến lược luật |
| `active` | có | thành viên bình thường của ensemble |

> **Tại sao shadow/filter không nằm trong `self.strategies`:** allocator chuẩn hoá
> trọng số trên *danh sách* chiến lược. Chỉ việc có mặt trong danh sách — dù không
> bao giờ phát tín hiệu — đã kéo trọng số của `breakout` từ 1.00 xuống 0.60. Chế độ
> bóng lúc đó không còn là bóng nữa, nó đã âm thầm đổi quy mô lệnh thật. Muốn không
> ảnh hưởng gì thì phải **không có mặt**, chứ không phải có mặt rồi tự hứa sẽ im lặng.
> Bất biến này được khoá bằng `tests/test_main_policy.py`.

Đổi chế độ là **quyết định của người**. Vòng học được phép đổi champion *trong* một
chế độ; nó không bao giờ được tự nâng chế độ lên.

---

## 6. Học từ kết quả quyết định trước — và cái bẫy trong đó

Nghe hợp lý: "cho model học từ những lệnh nó đã vào". Đó là cái bẫy.

Ta chỉ có kết quả của những lệnh **đã vào**, tức mẫu đã bị lọc bởi chính mô hình cũ.
Mô hình mới sẽ học cách củng cố thói quen của mô hình cũ thay vì học thị trường, và
sai lệch tự khuếch đại qua mỗi vòng.

Cách làm ở đây:

- **Nhãn huấn luyện** luôn là triple-barrier tính cho **mọi cây nến** — có sẵn dù ta
  có vào lệnh hay không. Không có thiên lệch chọn mẫu.
- **Kết quả lệnh thật** chỉ dùng để **theo dõi** và **hạ cấp**, không bao giờ để
  huấn luyện.
- Bảng `policy_predictions` ghi **cả những lần policy nói HOLD**, kèm kết quả phản
  thực tế ("nếu vào lệnh lúc đó thì sao"). Nhờ vậy hồ sơ kết quả trực tuyến không bị
  lệch về phía những quyết định đã được chọn.

---

## 7. Cách chạy

```bash
python run_policy.py hoc          # một vòng học: huấn luyện + chấm cổng
python run_policy.py trang-thai   # champion, lịch sử phiên bản, kết quả thật
python run_policy.py the          # đọc thẻ mô hình của champion
python run_policy.py theo-doi     # điền kết quả thật + kiểm tra hạ cấp
python run_policy.py ha-cap --ly-do "..."
```

`theo-doi` cũng tự chạy mỗi ngày một lần bên trong `main.py`, nên đường hạ cấp không
phụ thuộc vào việc có ai nhớ bật nó hay không.

---

## 8. Kết quả lần chạy đầu tiên (2026-09-06, mainnet 4H, 22 mã)

```
AUC trung bình      0.627   (đối chứng nhãn xáo trộn: 0.511 — đường ống sạch)
IC cắt ngang        0.078   t = 2.61 (đã hiệu chỉnh)
Số lệnh trên val    0       <- TRƯỢT
```

**Mô hình xếp hạng được, nhưng không có nến nào đáng vào lệnh.** Con số cụ thể:

| | |
|---|---|
| Tỷ lệ cơ sở `ret_long > 0` | 0.3949 |
| p_long mô hình dự đoán | 0.3951 … **0.4195** (max trên 15.096 nến) |
| p cần để hoà vốn sau phí | **0.432** |

Với TP = 3×ATR, SL = 2×ATR và chi phí vòng 0.3%, ngưỡng hoà vốn là 0.432. Dự đoán
tự tin nhất của mô hình đạt 0.4195 — **thiếu khoảng 1,3 điểm phần trăm**, trên toàn
bộ 15.096 nến kiểm định.

Đó là con số đo được khoảng cách còn lại: không phải "không học được gì" (IC 0.078,
t 2.61 là có thật), mà là **khả năng xếp hạng chưa đủ để vượt hàng rào chi phí**.
Hai đường đi từ đây, theo thứ tự ưu tiên:

1. **Hạ hàng rào**: phí maker thay vì taker, hoặc barrier rộng hơn để chi phí cố
   định chiếm tỷ trọng nhỏ hơn trong mỗi lệnh.
2. **Nâng khả năng xếp hạng**: nguồn dữ liệu mới. Ba nguồn tải lại được (OHLCV,
   funding, OI) đều đã đo và đều không đủ. Sổ lệnh là nguồn duy nhất chưa thử, và
   nó không tải lại được — phải thu thập tới.

Cổng từ chối mô hình này. Đó là kết quả **đúng**, không phải lỗi.
