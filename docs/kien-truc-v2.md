# AI Trade Bot cho Bybit — Kiến trúc v2 (bản nâng cấp)

## Tại sao cần nâng cấp v1

Bản v1 mô tả đúng các thành phần cơ bản, nhưng nó mắc ba lỗi mà gần như mọi bot trade retail đều mắc.

Thứ nhất, nó đặt LLM vào vị trí sinh tín hiệu mua/bán — đúng vị trí mà LLM yếu nhất. Thứ hai, nó chạy một chiến lược cố định cho mọi điều kiện thị trường, trong khi crypto đổi chế độ (xu hướng / đi ngang / hoảng loạn) liên tục. Thứ ba, nó coi backtest là bước kiểm tra hình thức, trong khi backtest sai chính là nguyên nhân số một khiến bot lãi trên giấy và lỗ ngoài đời.

Bản v2 sửa cả ba, và thêm hai thứ v1 thiếu hoàn toàn: một vòng lặp học hỏi, và độ bền vận hành.

## Nâng cấp 1 — Đặt LLM vào đúng ghế

Đây là thay đổi quan trọng nhất của bản v2.

Phép tính về độ trễ: một tin lớn (ETF được duyệt, sàn bị hack, Fed phát biểu) được phản ánh vào giá BTC trong khoảng vài trăm mili-giây đến vài giây, bởi các hệ thống đọc thẳng từ nguồn. Đường đi của bot chúng ta: nguồn tin RSS/API cập nhật (30 giây đến vài phút) → gọi LLM (2-10 giây) → parse kết quả → quyết định → gửi lệnh (~200ms). Tổng cộng chậm hơn thị trường từ vài chục giây đến vài phút. Ở khung đó, "giao dịch theo tin tức" không phải là đi trước thị trường, mà là mua đúng đỉnh của cú nhảy tin — đúng chỗ những người vào trước đang thoát hàng.

Kết luận không phải là bỏ LLM. Kết luận là LLM không nên trả lời câu hỏi "mua hay bán", mà nên trả lời bốn câu hỏi khác, nơi nó thực sự có lợi thế:

**(a) Bộ lọc phủ quyết (veto filter).** Trước khi một lệnh do tín hiệu kỹ thuật sinh ra được gửi đi, LLM đọc bối cảnh 24 giờ gần nhất và trả lời: có sự kiện nào khiến vào lệnh này là ngu ngốc không? Sàn đang có sự cố rút tiền? Stablecoin mất peg? Một dự án lớn vừa bị hack? LLM không cần nhanh để làm việc này — nó chỉ cần đúng. Đây là loại câu hỏi mà chỉ báo kỹ thuật hoàn toàn mù, vì chỉ báo không biết đọc tin.

**(b) Phân loại chế độ thị trường (regime).** Thị trường đang trending mạnh, tích lũy đi ngang, biến động cao hoảng loạn, hay phục hồi sau sụp đổ? Kết hợp tín hiệu định lượng (ADX, ATR percentile, độ tự tương quan của return) với bối cảnh tường thuật mà LLM đọc được.

**(c) Nhà nghiên cứu ngoại tuyến** — xem Nâng cấp 5.

**(d) Người viết nhật ký giao dịch** — xem Nâng cấp 6.

Ở cả bốn vai trò này, độ trễ vài giây đến vài phút không quan trọng. Đó chính là lý do chúng hợp với LLM, còn việc bấm nút mua/bán theo tin thì không.

## Nâng cấp 2 — Nhiều chiến lược đơn giản + chuyển theo regime

Một chiến lược phức tạp thắng trong một loại thị trường sẽ thua trong loại khác. Ba chiến lược đơn giản, ít tương quan, cộng một bộ phân bổ trọng số, bền hơn nhiều.

Bộ ba tối thiểu: **trend-following** (EMA cross kèm lọc ADX, ăn khi thị trường có xu hướng), **mean-reversion** (RSI/Bollinger ở vùng cực trị, ăn khi thị trường đi ngang), và **breakout** (kênh Donchian kèm xác nhận khối lượng, ăn khi giá thoát vùng tích lũy).

Điểm mấu chốt là ba chiến lược này lỗ ở những thời điểm khác nhau. Trend-following bị cưa liên tục trong sideway; mean-reversion bị nghiền nát khi có xu hướng mạnh. Chạy cả ba với trọng số thay đổi theo regime cho đường vốn mượt hơn bất kỳ chiến lược đơn lẻ nào, kể cả chiến lược có lợi nhuận kỳ vọng cao hơn.

Bộ phân bổ gán trọng số theo regime hiện tại và hiệu suất cuốn chiếu 30-60 ngày, có sàn và trần (ví dụ mỗi chiến lược từ 10% đến 60%) để không dồn hết vốn vào chiến lược vừa gặp may.

## Nâng cấp 3 — Kích thước lệnh theo biến động, không theo phần trăm cố định

v1 dùng "mỗi lệnh 5% vốn". Vấn đề: 5% vốn vào BTC lúc biến động 2%/ngày và 5% vốn vào một altcoin biến động 15%/ngày là hai mức rủi ro khác nhau hoàn toàn, dù con số nhìn giống nhau.

Cách đúng là cố định **rủi ro** mỗi lệnh chứ không cố định giá trị lệnh. Đặt stop-loss theo ATR (ví dụ 2×ATR14 tính từ giá vào), rồi tính khối lượng sao cho nếu chạm stop thì mất đúng R% vốn, với R thường trong khoảng 0.5%-1%. Khi biến động cao, khối lượng tự động nhỏ lại; khi biến động thấp, nó lớn lên. Riêng thay đổi này đã làm đường vốn mượt hơn rõ rệt so với sizing cố định.

Thêm hai giới hạn cấp danh mục mà v1 không có. **Portfolio heat**: tổng rủi ro của tất cả lệnh đang mở không vượt quá khoảng 3% vốn, bất kể có bao nhiêu tín hiệu đẹp cùng lúc. **Trần tương quan**: BTC và ETH tương quan khoảng 0.85-0.9, nên mở ba lệnh long BTC, ETH và SOL không phải là đa dạng hóa mà là một lệnh gấp ba lần. Rủi ro phải tính theo cụm tương quan, không theo từng mã riêng lẻ.

## Nâng cấp 4 — Backtest trung thực

Đây là nơi phần lớn bot chết, và chết trước khi kịp biết mình đã chết.

**Chi phí phải nằm trong backtest.** Bybit spot taker khoảng 0.1%, futures taker khoảng 0.055%, cộng slippage và (với futures) funding rate mỗi 8 giờ. Một vòng mua-bán trên spot tốn khoảng 0.2%. Một chiến lược nhắm biến động 0.3% mỗi lệnh nghe rất hấp dẫn, cho đến khi trừ phí: nó chỉ còn thực lãi 0.1%, và chỉ cần tỷ lệ thắng lệch đi một chút là âm. Rất nhiều "chiến lược thắng" biến mất sạch khi cộng phí vào. Backtest chưa trừ phí và slippage thì kết quả không có ý nghĩa gì.

**Lookahead bias.** Tính chỉ báo trên cây nến hiện tại chưa đóng là tự lừa mình. Mọi quyết định chỉ được dùng dữ liệu đã tồn tại tại thời điểm đó: nến đã đóng, tin đã công bố.

**Walk-forward thay vì backtest một lần.** Tối ưu tham số trên toàn bộ lịch sử rồi khoe kết quả là overfit kinh điển. Cách đúng: tối ưu trên 6 tháng, kiểm định trên 2 tháng kế tiếp, trượt cửa sổ về phía trước, lặp lại nhiều lần. Chỉ phần out-of-sample mới đáng tin.

**Cổng thống kê trước khi cho lên live.** Một chiến lược chỉ được promote nếu vượt qua tất cả: tối thiểu 100 lệnh out-of-sample, Sharpe out-of-sample trên 1.0, max drawdown dưới 20%, profit factor trên 1.3, có lãi ở ít nhất 2 trong 3 regime, và hiệu suất out-of-sample không tệ hơn 50% so với in-sample (chênh lệch lớn hơn thế gần như chắc chắn là overfit).

## Nâng cấp 5 — Strategy Lab: LLM sinh giả thuyết, máy kiểm định

Đây là cách dùng LLM để đi tìm lợi thế mà không cho nó chạm vào tiền thật.

Vòng lặp chạy ngoại tuyến, mỗi tuần một lần. LLM đọc log giao dịch, dữ liệu thị trường gần đây và danh sách chiến lược hiện có, rồi đề xuất giả thuyết mới dưới dạng code — ví dụ "khi funding rate âm sâu và RSI khung 4h dưới 30, lệnh long có lợi thế". Hệ thống tự động backtest walk-forward giả thuyết đó. Nếu vượt cổng thống kê ở Nâng cấp 4, nó được đưa vào shadow mode: giao dịch giấy chạy song song với bot thật trong 2-4 tuần. Nếu shadow mode vẫn tốt, nó mới được thêm vào ensemble với trọng số nhỏ.

Điểm hay của thiết kế này là LLM được tự do sáng tạo và được phép sai thoải mái, vì giữa nó và tiền thật có hai lớp kiểm định tự động. Ý tưởng tồi bị loại bởi số liệu, không phải bởi cảm tính của ai.

## Nâng cấp 6 — Vòng học hỏi hằng đêm

Mỗi đêm, một tác vụ chạy: LLM đọc toàn bộ lệnh trong ngày kèm lý do vào/ra, kết quả và bối cảnh thị trường, rồi viết một bản phê bình ngắn. Lệnh nào sai, và sai vì chiến lược sai, vì thực thi tệ, hay chỉ vì xui? Tín hiệu nào lặp đi lặp lại mà luôn thua? Có mẫu hình nào đang hình thành?

Đây là thứ gần như không bot retail nào có, và là nơi LLM tạo giá trị rõ ràng nhất: nó đọc được lịch sử giao dịch của chính bạn theo cách mà một bảng số liệu không nói ra. Sau ba tháng, tập hợp các bản phê bình này có khi đáng giá hơn cả chiến lược ban đầu.

Bản phê bình được ghi vào database và gửi qua Telegram. Nó không có quyền tự động sửa tham số — con người đọc rồi quyết định. Để LLM tự chỉnh tham số dựa trên kết quả ngắn hạn là con đường ngắn nhất dẫn đến overfit theo thời gian thực.

## Nâng cấp 7 — Độ bền vận hành

Bot chết vì lỗi vận hành nhiều hơn vì chiến lược sai.

**Đối soát trạng thái khi khởi động.** Kịch bản kinh điển: bot crash lúc đang giữ vị thế, khởi động lại, không biết mình đang có lệnh, và mở thêm lệnh nữa. Nguyên tắc: nguồn sự thật là sàn, không phải file local. Mỗi lần khởi động phải đọc vị thế và lệnh chờ thực tế từ Bybit, đối chiếu với database, và nếu lệch thì dừng lại báo người chứ không đoán.

**Idempotency.** Mọi lệnh gửi đi kèm `orderLinkId` sinh xác định. Timeout mạng không có nghĩa là lệnh chưa vào sàn — retry mù là cách chắc chắn nhất để tạo lệnh trùng.

**Circuit breakers rộng hơn v1:** dữ liệu cũ quá ngưỡng giây, spread bất thường, giá nhảy quá N lần ATR trong một nến, API trả lỗi liên tiếp, funding rate cực đoan, drawdown ngày chạm ngưỡng, và số lệnh thua liên tiếp vượt ngưỡng. Chạm bất kỳ điều kiện nào thì dừng mở lệnh mới, báo Telegram và chờ người — không tự đóng các lệnh đang có, trừ trường hợp drawdown.

**Bảo mật API key.** Key chỉ bật quyền giao dịch, **tắt quyền rút tiền**, và bật IP whitelist trỏ về IP của VPS. Đây là biện pháp bảo vệ đáng giá nhất trong toàn hệ thống: nếu key bị lộ mà không có quyền rút tiền thì thiệt hại bị giới hạn. Key nằm trong `.env` và không bao giờ được commit.

**Chạy trên VPS, không chạy trên máy cá nhân.** Máy cá nhân sẽ ngủ, mất điện, mất mạng, hoặc Windows update lúc 3 giờ sáng — trong khi vị thế vẫn đang mở. VPS đặt ở Singapore (gần hạ tầng Bybit), chạy Docker hoặc systemd với restart policy, kèm một watchdog kiểm tra heartbeat.

## Kiến trúc phân lớp v2

Dữ liệu và đối soát (L0) → đặc trưng kỹ thuật, biến động, vi cấu trúc (L1) → phân loại regime (L2) → ensemble chiến lược (L3) → bộ phân bổ trọng số (L4) → LLM veto filter (L5) → risk engine với ATR sizing, portfolio heat, trần tương quan và circuit breakers (L6) → thực thi ưu tiên lệnh maker để tiết kiệm phí, kiểm soát slippage (L7) → quan sát: log, metrics, Telegram (L8) → học hỏi: post-mortem hằng đêm, Strategy Lab hằng tuần (L9).

Chú ý thứ tự: LLM veto nằm **sau** khi tín hiệu đã được sinh ra và **trước** risk engine. Nó chỉ có quyền phủ quyết hoặc giảm kích thước lệnh, không bao giờ có quyền tự tạo lệnh. Đây là ràng buộc kiến trúc quan trọng nhất của bản v2, và cũng là điểm khác biệt căn bản so với v1.

## Kỳ vọng thực tế

Phần lớn bot trade retail lỗ. Không phải vì người viết kém, mà vì phí cộng slippage cộng overfit cộng lỗi vận hành thường lớn hơn cái lợi thế mỏng manh mà một hệ thống đơn giản có thể tìm được, trong một thị trường đầy đối thủ chuyên nghiệp hơn nhiều.

Vì vậy tiêu chí đánh giá phiên bản đầu tiên không nên là lợi nhuận. Nên là: bot có thực thi đúng ý đồ không, có tuân thủ risk limit không, có sống sót qua crash và mất mạng không, và có sinh ra dữ liệu đủ sạch để học không. Nếu ba tháng đầu hòa vốn nhưng hệ thống chạy đúng và bạn có 500 lệnh được log tử tế kèm lý do, đó là thành công — vì từ đó mới cải thiện được. Một bot lãi ba tháng nhờ may mắn trong một đợt bull run mà không ai hiểu vì sao nó lãi thì nguy hiểm hơn nhiều, bởi nó sẽ khiến bạn tăng vốn ngay trước khi nó ngừng hoạt động.

Đây không phải lời khuyên đầu tư. Chỉ nên dùng số vốn có thể mất hoàn toàn mà không ảnh hưởng đến cuộc sống.

## Lộ trình v2

**Giai đoạn 1 (2-3 tuần):** hạ tầng, một chiến lược trend-following, và backtest walk-forward trung thực có tính phí. Mục tiêu là có một baseline đáng tin, chưa cần AI.

**Giai đoạn 2 (2 tuần):** risk engine đầy đủ (ATR sizing, portfolio heat, circuit breakers) và đối soát trạng thái. An toàn trước, thông minh sau.

**Giai đoạn 3 (2 tuần):** thêm hai chiến lược còn lại, regime classifier và bộ phân bổ.

**Giai đoạn 4 (2 tuần):** LLM veto filter và nhật ký AI hằng đêm. Đây mới là lúc "AI" thực sự bước vào hệ thống.

**Giai đoạn 5 (4 tuần):** chạy full-auto trên testnet 24/7, không can thiệp tay. Mục tiêu duy nhất là chạy đúng và không sập.

**Giai đoạn 6:** live trên Spot với vốn nhỏ, giữ shadow mode chạy song song.

**Giai đoạn 7:** Strategy Lab, và chỉ khi mọi thứ phía trên đã ổn định mới tính đến futures với đòn bẩy thấp.

Khác biệt lớn nhất so với lộ trình v1: AI vào ở giai đoạn 4 chứ không phải giai đoạn 1. Hạ tầng và quản trị rủi ro phải đúng trước đã, vì AI gắn lên một nền móng lỏng lẻo chỉ làm bot mất tiền nhanh hơn và theo cách khó hiểu hơn.
