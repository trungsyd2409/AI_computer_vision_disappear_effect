# Disappear Effect – chụm 2 ngón tay để biến mất

Webcam app (Python + OpenCV + MediaPipe). Chạm **ngón cái + ngón trỏ tay phải** vào nhau → người mờ dần rồi biến mất, nền phía sau vẫn còn. Tách 2 ngón ra → người hiện lại.

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
| **B** | Chụp nền: đếm ngược 3s → bước ra khỏi khung hình → app lấy trung bình 15 khung hình |
| **X** | Mở / đóng cửa sổ Settings |
| **Q** / Esc | Thoát (settings tự lưu vào `settings.json`) |

## Cách dùng

1. `python main.py` → góc trên trái hiện *"No background! Press B to capture"*.
2. (Khuyên dùng) Bấm **X** → tab Camera → **Auto exposure = Off**, **Auto white balance = Off**, chỉnh slider cho vừa sáng. Nếu để auto, camera tự đổi độ sáng khi bạn bước ra/vào → nền đã chụp bị lệch màu so với hình live.
3. Bấm **B**, bước ra khỏi khung hình trong 3 giây, đợi chữ "Capturing background..." tắt.
4. Quay lại, giơ tay phải: chạm ngón cái + trỏ → biến mất; tách ra → hiện lại.

Hiển thị trên màn hình:
- **FPS** góc trên phải (dòng nhỏ `cam` = FPS thật của camera).
- **Opacity %** góc dưới trái và cạnh ngón tay (100% = hiện rõ, 0% = biến mất).
- Xương tay (21 điểm) + đường nối ngón cái–ngón trỏ: **xanh lá** = đang tách, **đỏ** = đang chạm.

## Cách hoạt động

```
camera thread ──► frame mới nhất
                    │ resize giữ tỷ lệ (tối đa 800x600) + lật gương
                    ├─► HandLandmarker ──► pinch ratio = |ngón cái - ngón trỏ| / cỡ bàn tay
                    │                        └─► chạm / tách (có hysteresis) ──► fade opacity
                    ├─► ImageSegmenter ──► mask người (làm mịn, nới rộng, viền mềm)
                    └─► output = nền_đã_chụp * mask * (1 - opacity) + live * (phần còn lại)
```

- **Chỉ vùng có người** bị thay bằng nền đã chụp, phần còn lại vẫn là hình live.
- **Pinch ratio** chia cho cỡ bàn tay nên đưa tay gần hay xa camera đều chạy đúng. Chạm khi `< 0.22`, chỉ tách khi `> 0.32` → không bị nhấp nháy ở ngưỡng.
- Camera đọc trong **thread riêng** (DirectShow + MJPG) để đạt 30 fps. Nếu FPS thấp: X → Codec = MJPG, FPS = 30, bấm Apply.

## Cửa sổ Settings (X)

**Tab Camera**: index, backend (DSHOW/MSMF), độ phân giải, FPS, codec · Auto exposure / white balance / focus · slider brightness, contrast, saturation, hue, gain, sharpness, gamma, backlight, exposure, white balance, focus. Tick **Set** thì app mới điều khiển thông số đó; cột `cam:` là giá trị camera đang báo lại (`n/a` = webcam không hỗ trợ). Nút **Webcam driver dialog** mở hộp thoại gốc của driver.

**Tab Effect**: tay điều khiển, ngưỡng chạm/tách (có dòng *Current ratio* để chỉnh theo tay bạn), khi mất tay, thời gian fade, model segmentation, chất lượng mask, countdown, lật gương, bật/tắt xương tay.

## Xử lý sự cố

| Hiện tượng | Cách sửa |
|---|---|
| Còn viền mờ quanh người khi biến mất | Tăng *Grow mask* (10–20 px) hoặc đổi model sang *multiclass* |
| Mép người nhấp nháy | Tăng *Temporal smoothing* (0.6–0.8) |
| Vùng bị mất bị ngược (nền biến mất thay vì người) | Tick *Invert mask* |
| Nền bị lệch màu khi biến mất | Tắt auto exposure / auto WB rồi chụp lại nền (B) |
| Hay bị "chạm" nhầm | Giảm *Touch when ratio <* |
| "Background size changed" | Đã đổi độ phân giải → bấm B chụp lại |
| Slider exposure không có tác dụng | Đổi `auto_exposure_on_value` / `auto_exposure_off_value` trong `settings.json` (MSMF: 0.75 / 0.25), hoặc dùng driver dialog |
| Không tải được model | Tải tay theo link in ra trong terminal, bỏ vào `models/` |

**Giới hạn**: bóng của bạn trên tường không biến mất (model chỉ tách người); không được di chuyển camera sau khi chụp nền.

## Cấu trúc code

| File | Nội dung |
|---|---|
| `main.py` | Vòng lặp chính, phím tắt |
| `camera.py` | Thread đọc webcam + áp thông số camera |
| `vision.py` | MediaPipe HandLandmarker + ImageSegmenter (Tasks API), tự tải model |
| `effect.py` | Pinch, fade, làm mịn mask, ghép ảnh, chụp nền |
| `overlay.py` | Vẽ FPS, opacity, xương tay, cảnh báo, countdown |
| `settings_ui.py` | Cửa sổ Settings (Tkinter) |
| `config.py` | Giá trị mặc định + load/save `settings.json` |
