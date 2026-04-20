<!-- @format -->

# TÀI LIỆU KỸ THUẬT: HỆ THỐNG SINH CÂU HỎI TƯƠNG TỰ BẰNG VERTEX AI

## 1. TỔNG QUAN HỆ THỐNG

Dự án "Sinh Câu Hỏi Tương Tự" là một ứng dụng Desktop được phát triển trên nền tảng PyQt5, tích hợp sức mạnh của Google Vertex AI (cụ thể là mô hình Gemini 2.5 Pro).

Mục tiêu cốt lõi của phần mềm là tự động hóa quy trình nhân bản và biến đổi định dạng câu hỏi từ cơ sở dữ liệu (CSDL) gốc. Hệ thống có khả năng phân tích nền tảng kiến thức của một câu hỏi đầu vào, từ đó nội suy và sinh ra các câu hỏi hoàn toàn mới nhưng ở các định dạng kiểm tra khác nhau (Trắc nghiệm, Đúng/Sai, Trả lời ngắn, Tự luận) theo tỷ lệ phần trăm được cấu hình sẵn.

### Chi tiết Dữ liệu Đầu vào và Đầu ra

- Đầu vào (Input):
  - Tap tin JSON trích xuất từ CSDL hệ thống (chứa câu hỏi gốc, metadata, ID, đơn vị kiến thức).
  - Tap tin Text (.txt) chứa Lệnh Khởi Tạo (System Prompt) định hình vai trò và luật chung cho AI.
  - Các tập tin Text (.txt) chứa Lệnh Quy Định Định Dạng (Format Prompt) riêng biệt cho từng loại câu hỏi.
- Đầu ra (Output):
  - Tap tin JSON: Chứa toàn bộ câu hỏi đã được sinh mới, tuân thủ nghiêm ngặt Schema của hệ thống.
  - Tap tin DOCX: Tài liệu Word đã được kết xuất (render) hoàn chỉnh, tự động xử lý hình ảnh và biên dịch các công thức Toán học (LaTeX) sang định dạng OMML tiêu chuẩn của Microsoft Word.

---

## 2. KIẾN TRÚC MÃ NGUỒN VÀ CHỨC NĂNG MODULE

### Sơ đồ cấu trúc thư mục

Cấu trúc tổ chức tập tin của dự án được sắp xếp như sau:

```
SinhCauHoiTuongTu/
├── Prompt sinh câu hỏi TIẾNG VIỆT/     # Thư mục chứa các mẫu lệnh văn bản cấu hình AI
│ ├── promptDungSai.txt                 # Lệnh quy định cấu trúc cho câu hỏi Đúng/Sai
│ ├── promptKhoiTao_V1.txt              # Lệnh khởi tạo bối cảnh và vai trò hệ thống
│ ├── promptTracNghiem.txt              # Lệnh quy định cấu trúc cho câu hỏi Trắc nghiệm
│ ├── promptTraLoiNgan.txt              # Lệnh quy định cấu trúc cho câu hỏi Trả lời ngắn
│ └── promptTuLuan.txt                  # Lệnh quy định cấu trúc cho câu hỏi Tự luận
├── generated_similar/                  # Thư mục mặc định chứa các tệp tin đầu ra sau khi sinh
│ ├── VATLITHPT2_1_1_converted.docx     # Tệp tin Word (DOCX) kết quả mẫu
│ ├── VATLITHPT2_1_1_converted.json     # Tệp tin JSON kết quả mẫu tuân thủ Schema
│ ├── toan_thpt_3_12_4_converted.docx   # Tệp tin Word (DOCX) kết quả mẫu
│ └── toan_thpt_3_12_4_converted.json   # Tệp tin JSON kết quả mẫu tuân thủ Schema
├── genques/                            # Thư mục chứa các module lõi xử lý logic nội bộ
│ ├── response2docxTN.py                # Module biên dịch LaTeX, định dạng Word và xuất DOCX
│ ├── schema.py                         # Module khai báo cấu trúc JSON bắt buộc AI phải trả về
│ └── text2Image.py                     # Module gọi API tạo hình ảnh từ văn bản mô tả
├── .env                                # Tệp tin ẩn cấu hình môi trường (Chứa khóa API Google Cloud - Cần tự tạo)
├── README.MD                           # Tài liệu hướng dẫn kỹ thuật và kiến trúc (Tệp tin này)
├── app_clone_questions.py              # Mã nguồn phụ trợ cho tính năng nhân bản câu hỏi
├── app_similar_question_debug.py       # Mã nguồn chuyên dụng dành cho quá trình gỡ lỗi (Debug)
├── app_similar_questions.py            # Tập tin khởi chạy chính - Nơi chứa mã nguồn giao diện (PyQt5)
├── callAPI.py                          # Module phụ trách xác thực, kết nối và giao tiếp với Google Vertex AI
├── requirements.txt                    # Danh sách các thư viện Python phụ thuộc cần cài đặt
└── split_json.py                       # Mã nguồn công cụ phụ trợ để chia nhỏ các file JSON lớn
```

### Chức năng chi tiết của các Module chính

Hệ thống được thiết kế theo hướng module hóa (Modular Design) để tối ưu khả năng bảo trì:

1. app_similar_questions.py (Core & GUI)

- Quản lý giao diện người dùng (PyQt5) và tiếp nhận các thiết lập từ người vận hành.
- Khởi tạo tiến trình Đa luồng (ThreadPoolExecutor) thông qua lớp ConversionWorker.
- Xử lý thuật toán phân bổ tỷ lệ dạng bài: Tính toán Quota dựa trên số lượng câu hỏi đầu vào và tỷ lệ % người dùng yêu cầu, ưu tiên gán định dạng sao cho phân bổ đồng đều.
- Xử lý làm sạch dữ liệu ban đầu (Regex bóc tách chuỗi ObjectId, NumberInt thừa từ CSDL cũ).

2. callAPI.py (AI Connector)

- Chịu trách nhiệm khởi tạo Client kết nối với Google Cloud Vertex AI thông qua thư viện `google-genai`.
- Đọc file `.env` (Service Account Credentials).
- Cho phép gửi ngữ cảnh đính kèm (PDF, Markdown) cùng với Text Prompt lên hệ thống AI.

3. genques/response2docxTN.py (Rendering Engine)

- Tiếp nhận chuỗi JSON do AI trả về, thực hiện bóc tách (Parsing) và cứu hộ dữ liệu (Salvage Data) nếu JSON bị lỗi cú pháp.
- Module DynamicDocxRenderer chịu trách nhiệm vẽ (render) cấu trúc câu hỏi, lời giải, gợi ý lên file Word.
- Tích hợp hàm `latex_to_omml_via_pandoc` sử dụng công cụ Pandoc để biên dịch các biểu thức nằm trong cặp dấu `$` thành công thức Word bản địa.

4. genques/schema.py (Data Validator)

- Chứa các định nghĩa JSON Schema bắt buộc cho AI. Hệ thống sử dụng cơ chế Schema Enforcement của Vertex AI để đảm bảo AI không trả về văn bản tự do, giúp duy trì tính ổn định khi kết xuất tài liệu.

5. genques/text2Image.py (Image Generator)

- Xử lý yêu cầu tạo hình ảnh. Nếu câu hỏi yêu cầu mô tả trực quan (co_hinh: true), module này sẽ gọi AI sinh ảnh dựa trên phần văn bản mô tả và chèn trực tiếp vào DOCX.

---

## 3. LUỒNG XỬ LÝ DỮ LIỆU CHI TIẾT (WORKFLOW)

Quy trình vòng đời của một tác vụ sinh câu hỏi diễn ra qua 5 giai đoạn:

- Giai đoạn 1: Chuẩn bị Dữ liệu (Data Preparation)
  Hệ thống tải file JSON. Nếu phát hiện file JSON không được bọc trong mảng `[]` (lỗi trích xuất ngầm), hệ thống sẽ tự động thêm dấu ngoặc để đảm bảo JSON hợp lệ. Dữ liệu sau đó được ánh xạ các thông tin Metadata (Level, ID, DVKT).

- Giai đoạn 2: Lập lịch và Phân bổ (Task Allocation)
  Từ tổng số câu hỏi, hệ thống dựa vào trọng số cấu hình trên UI (Ví dụ: 30% TN, 70% Tự luận) để tính toán chính xác số lượng slots cho mỗi định dạng. Sau đó, nó duyệt qua từng câu hỏi gốc và gán định dạng mục tiêu (Target Format) cùng với Lệnh cưỡng chế hình ảnh (Image Instruction).

- Giai đoạn 3: Thực thi Đa luồng (Multithreaded Execution)
  Khởi tạo 3 luồng (Workers) chạy song song. Mỗi luồng sẽ tổng hợp: Lệnh khởi tạo + Lệnh định dạng mục tiêu + Schema tương ứng + Câu hỏi gốc. Gửi request lên Vertex AI (Gemini 2.5 Pro) với tham số `max_output_tokens=65535` để tránh tràn bộ đệm.

- Giai đoạn 4: Hậu xử lý và Sửa lỗi (Post-processing & Fallback)
  Khi AI trả kết quả về:

* Hàm `strip_html_from_json` loại bỏ các thẻ HTML thừa để tránh lỗi định dạng file Word. (Lưu ý: Thẻ `<u>` và `<ins>` được chuyển thành ngoặc vuông `[...]` để phục vụ dạng bài tìm lỗi sai Tiếng Anh).
* Thuật toán `salvage_questions_from_broken_json` (đặc biệt trong dạng Đúng/Sai) sẽ cố gắng quét và bóc tách các Object JSON hợp lệ trong trường hợp AI sinh ra chuỗi JSON bị đứt gãy giữa chừng do quá dài.

- Giai đoạn 5: Kết xuất Tài liệu (Document Generation)
  Đánh lại Số thứ tự (STT) theo thứ tự tuần tự. Lưu file JSON chuẩn hoá. Cuối cùng, module DOCX quét qua từng Node dữ liệu, xử lý màu sắc, định dạng in đậm và biên dịch LaTeX (Pandoc) để lưu thành file `.docx` hoàn chỉnh.

---

## 4. CƠ CHẾ XỬ LÝ VÀ PHÂN BỔ HÌNH ẢNH TRONG SCHEMA (IMAGE LOGIC)

Thiết kế Schema của hệ thống yêu cầu rất nhiều object hình ảnh độc lập. Điều này xuất phát từ nhu cầu sư phạm chuyên sâu: Một câu hỏi kiểm tra hoàn chỉnh (đặc biệt là Toán, Lý, Hóa) thường không chỉ có một hình ảnh duy nhất.

### 4.1. Phân loại các khối hình ảnh trong Schema

Hệ thống chia hình ảnh thành 3 cấp độ tương ứng với 3 thành phần của một câu hỏi:

- "hinh_anh":
  Được chèn ngay dưới nội dung câu hỏi. Dùng để mô tả đề bài (Ví dụ: Sơ đồ mạch điện ban đầu, hình vẽ vật thể cơ học gốc).

- "hinh_anh_giai_thich":
  Được chèn riêng vào khu vực phần Lời giải. Dùng để minh họa cho các bước giải (Ví dụ: Biểu diễn thêm các vector lực, vẽ đường phụ trong hình học, đồ thị trạng thái biến thiên). AI phải tách biệt hình này với hình của đề bài.

- "hinh_anh_goi_y":
  Được chèn vào phần Gợi ý độc lập. Cung cấp hình ảnh mang tính chất tư duy (Mindmap, sơ đồ khối tóm tắt kiến thức) để học sinh tự suy luận ra đáp án.

### 4.2. Cấu trúc nội bộ của một Object Hình Ảnh

Mỗi object hình ảnh phía trên đều tuân thủ một cấu trúc lõi giống hệt nhau bao gồm các tham số:

- co_hinh (Boolean): Biến cờ (Flag) xác định xem tại vị trí này có bắt buộc sinh hình không (True/False).
- loai (String): Định nghĩa kiểu sinh hình, mặc định là "tu_mo_ta" để kích hoạt module text2Image.
- mo_ta (String): Mô tả hình ảnh siêu chi tiết bằng Tiếng Việt để AI Text-to-Image vẽ.
- mo_ta_en (String): Phiên bản mô tả bằng Tiếng Anh. Dùng cho luồng câu hỏi song ngữ (có kèm translate_en).

### 4.3. Cơ chế kích hoạt và An toàn (Fallback Mechanism)

Module response2docxTN.py thực thi hình ảnh rất chặt chẽ thông qua hàm "generate_or_get_image":

- Gọi API sinh ảnh: Nếu co_hinh là True và có nội dung trong mo_ta, hệ thống gửi lệnh qua genques/text2Image.py. Hình ảnh trả về dạng chuỗi Byte sẽ được chèn thẳng vào Word với kích thước chuẩn (rộng 3.5 Inches) và căn giữa.
- Cơ chế Fallback (Giữ chỗ - Placeholder): Nếu máy chủ sinh ảnh bị lỗi (Server Timeout), hoặc AI đặt co_hinh = True nhưng lại quên ghi nội dung mô tả, hệ thống sẽ KHÔNG báo lỗi crash phần mềm. Thay vào đó, nó sẽ in một dòng chữ cảnh báo In đậm, in nghiêng, màu đỏ vào file Word (Ví dụ: [VI: Cần chèn hình: ...]). Cơ chế này giúp giáo viên rà soát file Word có thể dễ dàng nhận biết vị trí cần chèn hình ảnh minh họa bổ sung bằng tay.

---

## 5. HƯỚNG DẪN CÀI ĐẶT MÔI TRƯỜNG

Để kế thừa và vận hành dự án, máy tính phát triển cần đáp ứng các yêu cầu sau:

1. Yêu cầu hệ thống:

- Python 3.10 trở lên.
- Pandoc: YÊU CẦU BẮT BUỘC để biên dịch công thức Toán. Cần cài đặt Pandoc vào hệ thống (System PATH) HOẶC đặt thư mục chứa file `pandoc.exe` cùng cấp với file script đang chạy.

2. Cài đặt thư viện Python:

- Mở Terminal/Command Prompt tại thư mục gốc của dự án và chạy lệnh:
  ```
  pip install -r requirements.txt
  ```

---

## 6. HƯỚNG DẪN VẬN HÀNH DÀNH

1. Khởi động phần mềm:
   Chạy lệnh `python app_similar_questions.py` từ Terminal. Giao diện PyQt5 sẽ hiển thị.

2. Cấu hình Thư mục Tập tin:

- File JSON Gốc: Bấm "Browse JSON..." và trỏ tới file ngân hàng câu hỏi trích xuất từ hệ thống.
- Lưu Kết Quả Vào: Chọn thư mục để lưu file JSON và DOCX sau khi sinh xong (Mặc định: thư mục `generated_similar`).

3. Nạp Prompt Hướng Dẫn:
   Người dùng cần trỏ đường dẫn tới 5 file text cấu hình AI (đã có sẵn trong thư mục dự án):

- Prompt Khởi Tạo (Quy định bối cảnh tổng quan).
- Prompt Trắc Nghiệm.
- Prompt Đúng/Sai.
- Prompt Trả Lời Ngắn.
- Prompt Tự Luận.
  (Hệ thống sẽ báo lỗi nếu thiếu các file này, do AI không có dữ liệu để học cấu trúc).

4. Thiết lập Tỷ lệ Đầu ra:

- Sử dụng các thanh quay (SpinBox) để thiết lập tỷ lệ sinh các dạng bài. (Ví dụ để 100 ở ô Trắc Nghiệm và 0 ở các ô còn lại nếu chỉ muốn sinh Trắc Nghiệm).
- Chỉnh tỷ lệ % Hình ảnh: Tỷ lệ câu hỏi bị ép buộc phải mô tả và sinh hình ảnh minh họa.

5. Chạy Tiến trình:
   Bấm nút "Bắt Đầu Tiến Trình AI". Theo dõi tiến độ tại thanh Progress Bar và bảng Log Console. Nếu Log hiển thị màu xanh nghĩa là quá trình thành công. Mở thư mục Đầu ra để kiểm tra kết quả.

---

## 7. LƯU Ý

- Quản lý Lỗi LaTeX: Hàm `clean_latex_math` trong `response2docxTN.py` chứa hàng loạt Regex để chuẩn hóa các lỗi gõ LaTeX thường gặp của AI (ví dụ escape sequence bị nhân đôi `\\\\frac`). Nếu phát hiện công thức nào không render được, cần bổ sung Regex xử lý vào hàm này trước khi gửi sang Pandoc.
- Giới hạn Token: Nếu CSDL gốc chứa câu hỏi quá dài, AI có thể trả về lỗi hoặc ngắt quãng JSON. Cần điều chỉnh `BATCH_SIZE` trong file kết xuất hoặc giảm số lượng câu hỏi trong file gốc.
- Quản lý Bộ nhớ: Hệ thống dùng `_FILE_LOCK` và `_OUTPUT_DIR_LOCK` (threading.RLock) để đảm bảo an toàn luồng khi nhiều thread cùng lúc thao tác ghi file vào ổ cứng. Không được vô hiệu hóa cơ chế này để tránh hiện tượng ghi đè tệp tin hỏng.
