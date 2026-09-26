# Disappear Effect – điều khiển bằng 2 tay

Webcam app (Python + OpenCV + MediaPipe), cửa sổ tên **App**. Khoảng cách **ngón cái – ngón trỏ** của mỗi tay điều khiển một thông số (chỉ áp dụng lên người, nền giữ nguyên):

| Tay | 2 ngón chạm nhau | Mở hết cỡ | Ở giữa |
|---|---|---|---|
| **Phải** → Opacity | 0% (biến mất, chỉ còn nền) | 100% (hiện rõ) | trong suốt tương ứng |
| **Trái** → Glitch | 0% (sạch) | 100% (glitch tối đa) | glitch tương ứng |

## Cài đặt (Windows, Python 3.10 / 3.11)

```bat
cd F:\Chunwan\SourceCode\AI\AI_computer_vision_disappear_effect
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Lần chạy đầu app tự tải model (~10 MB) vào thư mục `models/`.

## Phím tắt (bấm vào cửa sổ video trước)

| Phím | Chức năng |
|---|---|
| **G** | Chụp (lại) nền: đếm ngược 3s → bước ra khỏi khung hình → app lấy trung bình 15 khung hình. Nền được lưu vào `background.png` và **tự load ở lần chạy sau** |
| **X** | Mở / đóng cửa sổ Settings |
| **Q** / Esc | Thoát (settings tự lưu vào `settings.json`) |

## Cách dùng

1. `python main.py`. Lần đầu (chưa có `background.png`) góc trên trái hiện *"No background! Press G to capture"*. Những lần sau app tự load nền đã lưu, không cần chụp lại.
2. (Khuyên dùng) Bấm **X** → tab Camera → **Auto exposure = Off**, **Auto white balance = Off**, chỉnh slider cho vừa sáng. Nếu để auto, camera tự đổi độ sáng khi bạn bước ra/vào → nền đã chụp bị lệch màu so với hình live.
3. Bấm **G**, bước ra khỏi khung hình trong 3 giây, đợi chữ "Capturing background..." tắt.
4. Quay lại, mở/khép 2 ngón tay phải để chỉnh độ hiện, tay trái để chỉnh glitch.

Hiển thị trên màn hình:
- **FPS** góc trên phải (dòng nhỏ `cam` = FPS thật của camera).
- **Glitch %** (hồng) và **Opacity %** (xanh lá) ở góc dưới trái, và cạnh ngón tay của tay tương ứng.
- Xương tay (21 điểm) + đường nối ngón cái–ngón trỏ: **xanh lá** = tay phải, **hồng** = tay trái.

## Cách hoạt động

```
camera thread ──► frame mới nhất
                    │ resize giữ tỷ lệ (tối đa 800x600) + lật gương
                    ├─► HandLandmarker (2 tay) ──► ratio = |ngón cái - ngón trỏ| / cỡ bàn tay
                    │     value = (ratio - 0.2) / (1.0 - 0.2), kẹp trong 0..1, làm mượt
                    │     tay phải → opacity, tay trái → glitch
                    ├─► ImageSegmenter ──► mask người (làm mịn, nới rộng, viền mềm)
                    └─► vùng người = nền*(1-opacity) + người*opacity
                        + glitch: xé lát ngang, lát chớp tắt, lệch kênh R/B, scanline, nhiễu
```

- **Chỉ vùng có người** bị thay bằng nền đã chụp, phần còn lại vẫn là hình live.
- **Ratio** chia cho cỡ bàn tay nên đưa tay gần hay xa camera đều chạy đúng. Mặc định ratio `0.2` = 0%, `1.0` = 100%.
- Chưa có nền đã chụp thì opacity luôn 100% (không thể ẩn), nhưng glitch vẫn chạy trên hình live.
- Mất tay quá 0.3s: *Show person* → opacity về 100%, glitch về 0%; *Keep state* → giữ nguyên giá trị cuối.
- Camera đọc trong **thread riêng** (DirectShow + MJPG) để đạt 30 fps. Nếu FPS thấp: X → Codec = MJPG, FPS = 30, bấm Apply.

## Cửa sổ Settings (X)

**Tab Camera**: index, backend (DSHOW/MSMF), độ phân giải, FPS, codec · Auto exposure / white balance / focus · slider brightness, contrast, saturation, hue, gain, sharpness, gamma, backlight, exposure, white balance, focus. Tick **Set** thì app mới điều khiển thông số đó; cột `cam:` là giá trị camera đang báo lại (`n/a` = webcam không hỗ trợ). Nút **Webcam driver dialog** mở hộp thoại gốc của driver.

**Tab Effect**: ratio ứng với 0% và 100% (có dòng hiển thị ratio hiện tại của mỗi tay để chỉnh theo tay bạn), độ mượt, khi mất tay, độ mạnh glitch tối đa / độ xé / độ lệch màu, model segmentation, chất lượng mask, countdown, lật gương, bật/tắt xương tay.

## Xử lý sự cố

| Hiện tượng | Cách sửa |
|---|---|
| Còn viền mờ quanh người khi biến mất | Tăng *Grow mask* (10–20 px) hoặc đổi model sang *multiclass* |
| Mép người nhấp nháy | Tăng *Temporal smoothing* (0.6–0.8) |
| Vùng bị mất bị ngược (nền biến mất thay vì người) | Tick *Invert mask* |
| Nền bị lệch màu khi biến mất | Tắt auto exposure / auto WB rồi chụp lại nền (G) |
| Khép sát 2 ngón mà chưa về 0% | Tăng *Touching ratio* (xem ratio hiện tại trong tab Effect) |
| Mở hết cỡ mà chưa tới 100% | Giảm *Wide open ratio* |
| Giá trị bị rung | Tăng *Smoothing* |
| "Background does not fit this resolution" | Đã đổi tỷ lệ khung hình (vd. 4:3 ↔ 16:9) → bấm G chụp lại |
| Nền đã lưu bị lệch sáng / lệch vị trí | Ánh sáng phòng hoặc vị trí camera đã đổi → bấm G chụp lại |
| Glitch quá mạnh / quá nhẹ | Tab Effect → *Max strength*, *Slice tear*, *RGB split* |
| Slider exposure không có tác dụng | Đổi `auto_exposure_on_value` / `auto_exposure_off_value` trong `settings.json` (MSMF: 0.75 / 0.25), hoặc dùng driver dialog |
| Không tải được model | Tải tay theo link in ra trong terminal, bỏ vào `models/` |

**Giới hạn**: bóng của bạn trên tường không biến mất (model chỉ tách người); không được di chuyển camera sau khi chụp nền.

## Cấu trúc code

| File | Nội dung |
|---|---|
| `main.py` | Vòng lặp chính, phím tắt |
| `camera.py` | Thread đọc webcam + áp thông số camera |
| `vision.py` | MediaPipe HandLandmarker + ImageSegmenter (Tasks API), tự tải model |
| `effect.py` | Ratio → giá trị, làm mịn mask, glitch + ghép ảnh, lưu/load nền |
| `overlay.py` | Vẽ FPS, opacity, glitch, xương tay, cảnh báo, countdown |
| `settings_ui.py` | Cửa sổ Settings (Tkinter) |
| `config.py` | Giá trị mặc định + load/save `settings.json` |
