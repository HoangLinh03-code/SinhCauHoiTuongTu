import os
import sys
import json
import re
import random
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor, as_completed

# PyQt5 imports
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QTextEdit, 
    QComboBox, QProgressBar, QMessageBox, QGroupBox, QSplitter, QSpinBox
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal

# Import core API modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from callAPI import VertexClient, get_vertex_ai_credentials
from genques.schema import schema_dung_sai, schema_tra_loi_ngan, schema_tu_luan, schema_trac_nghiem
from genques.response2docxTN import DynamicDocxRenderer, find_pandoc_executable
from docx import Document

# ============================================================
# MAPPING MÔN HỌC TỪ PREFIX CỦA dvkt
# ============================================================
SUBJECT_MAP = {
    "VATLI": "Vật Lí", "TOAN": "Toán", "HOA": "Hóa Học",
    "SINH": "Sinh Học", "ANH": "Tiếng Anh", "TIENGANH": "Tiếng Anh",
    "VAN": "Ngữ Văn", "SU": "Lịch Sử", "DIA": "Địa Lí", "GDCD": "GDCD",
    "TIN": "Tin Học", "CONG_NGHE": "Công Nghệ",
}

def is_english_subject(dvkt: str) -> bool:
    """Kiểm tra xem câu hỏi có thuộc môn Tiếng Anh không (từ mã dvkt)"""
    dvkt_upper = dvkt.upper()
    return dvkt_upper.startswith("ANH") or dvkt_upper.startswith("TIENGANH")

def detect_subject_from_dvkt(dvkt: str) -> str:
    """Trích xuất tên môn học từ mã dvkt (VD: VATLITHPT2_1_1_1 → Vật Lí)"""
    dvkt_upper = dvkt.upper()
    for prefix, name in SUBJECT_MAP.items():
        if dvkt_upper.startswith(prefix):
            return name
    return "Không xác định"

def strip_html_tags(text):
    """Chuyển đổi HTML tags thông minh: <u>/<ins> → [text], xóa các tag còn lại, decode entities."""
    if not isinstance(text, str):
        return text
    # Chuyển <u>text</u> và <ins>text</ins> thành [text] (giữ nghĩa cho câu tìm lỗi sai)
    text = re.sub(r'<u>(.*?)</u>', r'[\1]', text, flags=re.IGNORECASE|re.DOTALL)
    text = re.sub(r'<ins>(.*?)</ins>', r'[\1]', text, flags=re.IGNORECASE|re.DOTALL)
    # Xóa toàn bộ block <style>...</style> cùng nội dung bên trong
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.IGNORECASE|re.DOTALL)
    # Xóa HTML comments <!-- ... -->
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    # Xóa các tag HTML còn lại (VD: <br>, <br/>, <b>, <i>, <p>, <div>, <span>, <em>, <strong>...)
    text = re.sub(r'<[^>]+>', '', text)
    # Decode HTML entities phổ biến
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&rsquo;', "'")
    text = text.replace('&lsquo;', "'")
    text = text.replace('&rdquo;', '"')
    text = text.replace('&ldquo;', '"')
    text = text.replace('&quot;', '"')
    text = text.replace('&ndash;', '–')
    text = text.replace('&mdash;', '—')
    text = text.replace('&amp;', '&')
    text = text.replace('&#39;', "'")
    text = text.replace('&gt;', '>')
    text = text.replace('&lt;', '<')
    # Xóa \r\n dư thừa → \n
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    # Xóa nhiều dòng trống liên tiếp
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Xóa khoảng trắng thừa ở đầu/cuối
    text = text.strip()
    return text

def strip_html_from_json(obj):
    """Đệ quy loại bỏ HTML tags khỏi tất cả giá trị string trong JSON."""
    if isinstance(obj, str):
        return strip_html_tags(obj)
    elif isinstance(obj, dict):
        return {k: strip_html_from_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [strip_html_from_json(item) for item in obj]
    return obj

def extract_image_metadata(item):
    """Quét trường explain/content/image của đề gốc, trích xuất mô tả hình ảnh nhúng.
    Trả về danh sách mô tả hình (VD: 'Bảng biến thiên', 'Đồ thị hàm số', 'Hình minh họa').
    Áp dụng cho TẤT CẢ các môn."""
    descriptions = []
    fields_to_scan = ['explain', 'content', 'goi_y']
    for field in fields_to_scan:
        text = item.get(field, '')
        if not isinstance(text, str):
            continue
        # Tìm tất cả thẻ <img> có base64
        img_tags = re.findall(r'<img[^>]*src=["\']data:image[^"\'>]*["\'][^>]*>', text, re.IGNORECASE | re.DOTALL)
        for img_tag in img_tags:
            # Trích xuất alt text nếu có
            alt_match = re.search(r'alt=["\']([^"\'>]*)["\']', img_tag, re.IGNORECASE)
            alt_text = alt_match.group(1).strip() if alt_match else ''
            # Phân loại hình ảnh dựa trên context xung quanh
            desc = _classify_image(text, img_tag, alt_text)
            descriptions.append(desc)
    # Kiểm tra trường image top-level
    image_val = item.get('image', '')
    if isinstance(image_val, str) and image_val and not image_val.startswith('data:') and image_val != '[REMOVED_TO_SAVE_TOKENS]':
        descriptions.append(f"Hình minh họa đề bài (URL: {image_val[:80]}...)")
    elif isinstance(image_val, str) and image_val.startswith('data:'):
        descriptions.append("Hình minh họa đề bài (base64 image)")
    return descriptions

def _classify_image(context_text, img_tag, alt_text):
    """Phân loại hình ảnh dựa trên ngữ cảnh xung quanh."""
    if alt_text:
        return f"Hình ảnh: {alt_text}"
    # Tìm text trước thẻ img để đoán loại hình
    idx = context_text.find(img_tag)
    if idx > 0:
        before_text = context_text[max(0, idx-200):idx].lower()
        if 'bảng biến thiên' in before_text or 'bang bien thien' in before_text:
            return "Bảng biến thiên (variation table)"
        elif 'đồ thị' in before_text or 'do thi' in before_text:
            return "Đồ thị hàm số (function graph)"
        elif 'hình vẽ' in before_text or 'hình bên' in before_text:
            return "Hình vẽ minh họa (illustration/diagram)"
        elif 'bảng' in before_text:
            return "Bảng số liệu (data table)"
    return "Hình ảnh minh họa (illustration)"

def fix_math_format(text):
    """
    Chuẩn hóa format công thức trong output AI về dạng $...$ chuẩn.
    Xử lý: \\(...\\), \\[...\\], \\\\(...\\\\), và các variant khác.
    """
    if not isinstance(text, str):
        return text

    # --- 1. \\(...\\) → $...$ (inline math) ---
    # Cả dạng \( và \\( (Python string)
    text = re.sub(r'\\\\\((.+?)\\\\\)', r'$\1$', text, flags=re.DOTALL)
    text = re.sub(r'\\\((.+?)\\\)', r'$\1$', text, flags=re.DOTALL)

    # --- 2. \\[...\\] → $...$ (display math → inline để Pandoc xử lý) ---
    text = re.sub(r'\\\\\[(.+?)\\\\\]', r'$\1$', text, flags=re.DOTALL)
    text = re.sub(r'\\\[(.+?)\\\]', r'$\1$', text, flags=re.DOTALL)

    # --- 3. Xóa ký tự rác Unicode thường lẫn vào công thức ---
    # Một số model sinh ra \u2009 (thin space), \u200b (zero-width space)...
    text = re.sub(r'[\u200b\u200c\u200d\u2009\u202f\ufeff]', '', text)

    # --- 4. Normalize $$...$$ → $...$ (display block không cần thiết) ---
    # Chỉ normalize khi không nằm ở đầu dòng độc lập
    def deblock_double_dollar(m):
        inner = m.group(1).strip()
        return f'${inner}$'
    text = re.sub(r'\$\$(.+?)\$\$', deblock_double_dollar, text, flags=re.DOTALL)

    return text

def fix_explanation_formatting(text):
    """Đảm bảo lời giải có xuống dòng đúng giữa các bước giải.
    Áp dụng cho TẤT CẢ các môn."""
    if not isinstance(text, str):
        return text
    # Danh sách cụm từ đánh dấu bước mới trong lời giải
    step_markers = [
        'Ta có', 'Suy ra', 'Do đó', 'Vậy', 'Lập bảng', 'Bảng biến thiên',
        'Khi đó', 'Từ đó', 'Mà', 'Nên', 'Theo đề bài', 'Theo giả thiết',
        'Áp dụng', 'Thay', 'Xét', 'Giải phương trình', 'Cho', 'Đặt',
        'Với', 'Điều kiện', 'Tập xác định', 'Đạo hàm', 'Gọi',
        'Diện tích', 'Thể tích', 'Chi phí', 'Doanh thu', 'Lợi nhuận',
        'Tốc độ', 'Vận tốc', 'Phương trình', 'Khoảng cách',
        # English step markers
        'We have', 'Therefore', 'Thus', 'Hence', 'Since', 'So',
        'Let', 'Given', 'Applying', 'Substituting',
    ]
    # Nếu text có ít newline (ít hơn 3), thêm \n trước mỗi step marker
    newline_count = text.count('\n')
    if newline_count < 3 and len(text) > 200:
        for marker in step_markers:
            # Chỉ thêm \n trước marker nếu nó đứng sau ký tự không phải \n
            pattern = r'([^\n])(' + re.escape(marker) + r')'
            text = re.sub(pattern, r'\1\n\2', text)
    return text

def fix_latex_escape_in_string(text: str) -> str:
    """
    Chuẩn hóa escape sequences trong chuỗi LaTeX sau khi JSON đã được parse.
    Gemini đôi khi sinh \\\\frac (4 backslash) thay vì \\frac (2 backslash).
    """
    if not isinstance(text, str):
        return text
    # Pattern: 4 backslash + lệnh LaTeX → 2 backslash (đúng)
    # Trong Python string: '\\\\\\\\' = 4 backslash thực → '\\\\' = 2 backslash
    text = re.sub(r'\\{4}([a-zA-Z()\[\]{}_^])', r'\\\\' + r'\1', text)
    return text


def post_process_clone_json(obj):
    """
    Áp dụng fix toàn diện cho output AI:
    1. Chuẩn hóa format công thức (\\(...\\) → $...$)
    2. Chuẩn hóa escape sequences LaTeX
    3. Chuẩn hóa xuống dòng lời giải
    Đệ quy xử lý tất cả string trong JSON.
    """
    if isinstance(obj, str):
        obj = fix_math_format(obj)
        obj = fix_latex_escape_in_string(obj)
        return obj
    elif isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            processed = post_process_clone_json(v)
            # Áp dụng fix_explanation_formatting cho trường giải thích dạng string
            if k == 'giai_thich' and isinstance(processed, str):
                processed = fix_explanation_formatting(processed)
            result[k] = processed
        return result
    elif isinstance(obj, list):
        return [post_process_clone_json(item) for item in obj]
    return obj

class ConversionWorker(QThread):
    progress_updated = pyqtSignal(int, int) # Current, Total
    log_message = pyqtSignal(str)
    process_finished = pyqtSignal(bool, str) # Success, Message

    def __init__(self, input_file, output_dir, format_prompts_dict, image_pct=10):
        super().__init__()
        self.input_file = input_file
        self.output_dir = output_dir
        self.format_prompts_dict = format_prompts_dict  # Dict: {format_name: prompt_text}
        self.is_cancelled = False
        self.image_pct = image_pct                 # % câu hỏi có hình ảnh (0-100)

    def build_final_prompt(self, item_json, target_format, image_instruction=""):
        # Tên hiển thị tiếng Việt của target format
        format_display = {
            "trac_nghiem_4_dap_an": "TRẮC NGHIỆM 4 ĐÁP ÁN (A, B, C, D)",
            "dung_sai": "ĐÚNG/SAI (4 mệnh đề a, b, c, d)",
            "tra_loi_ngan": "TRẢ LỜI NGẮN (Đáp án là MỘT CON SỐ duy nhất)",
            "tu_luan": "TỰ LUẬN (Bài toán giải chi tiết, đáp án cụ thể)"
        }
        target_display = format_display.get(target_format, target_format)

        # --- TRÍCH XUẤT MÔN HỌC TỪ dvkt ---
        detected_subject = detect_subject_from_dvkt(item_json.get("dvkt", ""))

        # --- PHÁT HIỆN MÔN TIẾNG ANH → DÙNG PROMPT CHUYÊN BIỆT ---
        dvkt = item_json.get("dvkt", "")
        if is_english_subject(dvkt):
            return self._build_english_prompt(item_json, target_format, target_display, detected_subject, image_instruction)
        
        return self._build_default_prompt(item_json, target_format, target_display, detected_subject, image_instruction)

    def _build_english_prompt(self, item_json, target_format, target_display, detected_subject, image_instruction):
        """Prompt chuyên biệt cho câu hỏi Tiếng Anh — thay đổi ngữ cảnh, giữ điểm kiến thức"""
        english_prompt_content = self.format_prompts_dict.get('tieng_anh', '')
        
        # --- XỬ LÝ LEVEL ĐỘ KHÓ ---
        level_raw = item_json.get('level', 'TH')
        level_display = {
            'NB': 'NHẬN BIẾT (đơn giản, kiến thức cơ bản)',
            'TH': 'THÔNG HIỂU (trung bình, cần hiểu quy tắc)',
            'VD': 'VẬN DỤNG (nâng cao, cần tổng hợp kiến thức)',
            'VDC': 'VẬN DỤNG CAO (khó nhất nhưng vẫn trong THPT B1-B2 CEFR)'
        }.get(level_raw, 'THÔNG HIỂU')
        
        return f"""Bạn là CHUYÊN GIA NGÔN NGỮ HỌC TIẾNG ANH kiêm MÁY SAO CHÉP CHUYÊN NGHIỆP.
Nhiệm vụ: TẠO BẢN SAO CHẤT LƯỢNG CAO cho câu hỏi Tiếng Anh cấp THPT dưới đây.


   MÔN HỌC: TIẾNG ANH — PROMPT CHUYÊN BIỆT              
                                                               
  → NỘI DUNG CÂU HỎI bằng TIẾNG ANH                        
  → GIẢI THÍCH bằng TIẾNG VIỆT                               
  → THAY ĐỔI NGỮ CẢNH câu, GIỮ NGUYÊN điểm kiến thức       
  → KHÔNG chỉ thay số (đây là Tiếng Anh, không phải Toán)    
  → KHÔNG vượt quá trình độ THPT (B1-B2 CEFR)               


   ĐỘ KHÓ BẮT BUỘC: {level_display}
  → Câu clone PHẢI có độ khó TƯƠNG ĐƯƠNG level "{level_raw}" của câu gốc.
  → KHÔNG ĐƯỢC tạo câu quá khó vượt trình độ học sinh THPT.


   LỆNH CƯỠNG CHẾ ĐỊNH DẠNG (FORMAT ENFORCEMENT)       
  BẠN BẮT BUỘC PHẢI XUẤT RA ĐÚNG DẠNG: {target_format:<30s}
  → Trường "loai_de" trong JSON output PHẢI = "{target_format}"
  → Cấu trúc "du_lieu" PHẢI tuân thủ SCHEMA của dạng này.    


==== HƯỚNG DẪN CLONE CHUYÊN BIỆT TIẾNG ANH ====
{english_prompt_content}

==== QUY TẮC BẮT BUỘC ====
1. NỘI DUNG CÂU HỎI viết bằng TIẾNG ANH. GIẢI THÍCH viết bằng TIẾNG VIỆT.
2. TRẢ VỀ JSON TUÂN THỦ CHÍNH XÁC SCHEMA của dạng "{target_format}".
3. BẮT BUỘC chép lại chính xác "_id" và "dvkt" từ json gốc sang câu hỏi mới.
4. GIỮ NGUYÊN điểm ngữ pháp/từ vựng đang kiểm tra, THAY ĐỔI ngữ cảnh câu.
5. GIẢI THÍCH phải GIÀU KIẾN THỨC: phân tích CẶN KẼ TỪNG phương án (cả đúng lẫn sai), nêu quy tắc, dấu hiệu nhận biết.
6. CUỐI CÙNG BẮT BUỘC có dòng: "**Tạm dịch:** *bản dịch tiếng Việt chuyên nghiệp*" (bold + italic).
7. BẮT BUỘC BỎ MỌI HTML TAG — output phải là plain text. KHÔNG chứa <p>, <style>, <span>, <br>, <div>, <em>, <strong>, etc.
8. Ô trống (blank) LUÔN dùng ĐÚNG 6 gạch dưới: ______
9. Câu tìm lỗi sai: BẮT BUỘC gạch chân từ/cụm từ cần xét bằng [từ] trong "noi_dung".
10. YÊU CẦU SINH CHUẨN TƯƠNG TỰ: Cấu trúc câu từ, độ dài, cách trình bày của câu hỏi mới PHẢI CHUẨN XÁC, TƯƠNG TỰ 100% với câu hỏi gốc. KHÔNG ĐƯỢC phép làm ngắn gọn đi hay tóm tắt lại.

==== HÌNH ẢNH ====
{image_instruction}

==== CÂU HỎI GỐC CẦN SAO CHÉP ====
`typeAnswer` (Loại đề gốc) là: {item_json.get('typeAnswer', 'Không rõ')}
`level` (Độ khó): {level_raw} — {level_display}

```json
{json.dumps(item_json, ensure_ascii=False)}
```

NHẮC LẠI: Output PHẢI là dạng "{target_format}" với "loai_de": "{target_format}".
Trả về ĐÚNG MỘT OBJECT JSON tuân thủ chính xác Schema của dạng "{target_format}".
"""

    def _build_default_prompt(self, item_json, target_format, target_display, detected_subject, image_instruction):
        """Prompt mặc định cho Toán/Lý/Hóa/Sinh... — chỉ thay số liệu"""
        return f"""Bạn là một MÁY SAO CHÉP (CLONER) CHUYÊN NGHIỆP. Nhiệm vụ TUYỆT ĐỐI BẮT BUỘC: TẠO BẢN SAO CHO CÂU HỎI DƯỚI ĐÂY.
1. GIỮ NGUYÊN HOÀN TOÀN CẤU TRÚC VÀ VĂN PHONG CỦA CÂU HỎI. 
2. CHỈ ĐƯỢC PHÉP thay đổi các SỐ LIỆU (bằng các số liệu khác hợp lý để ra kết quả đẹp) và TÊN ĐỐI TƯỢNG (nếu câu hỏi có yếu tố thực tế ban đầu).
3. TUYỆT ĐỐI KHÔNG ĐƯỢC biến một bài toán thuần túy thành bài toán thực tế (ví dụ: không được thêm câu chuyện về kiến trúc sư, kỹ sư, bác sĩ... nếu câu gốc không có). Nội dung câu hỏi mới phải Y HỆT câu hỏi gốc, chỉ khác những con số hoặc biểu thức.
4. CÁC CÔNG THỨC TOÁN HỌC phải giữ nguyên cấu trúc, chỉ thay thế các số.

KHÓA MÔN HỌC TUYỆT ĐỐI (SUBJECT LOCK)              
                                                              
MÔN HỌC: {detected_subject:<47s}
CẤP ĐỘ: TRUNG HỌC PHỔ THÔNG (THPT)                       
                                                              
→ TUYỆT ĐỐI KHÔNG tạo nội dung ngoài môn {detected_subject:<18s}
→ KHÔNG vượt quá chương trình THPT                         
→ KHÔNG lẫn sang bất kỳ môn nào khác                       
→ CẤM tạo câu chuyện/ngữ cảnh đời sống nếu câu gốc không có
   
LỆNH CƯỠNG CHẾ ĐỊNH DẠNG (FORMAT ENFORCEMENT)       
BẠN BẮT BUỘC PHẢI XUẤT RA ĐÚNG DẠNG: {target_format:<30s}
→ Trường "loai_de" trong JSON output PHẢI = "{target_format}"
→ Cấu trúc "du_lieu" PHẢI tuân thủ SCHEMA của dạng này.    


==== QUY ĐỊNH CHI TIẾT CHO DẠNG: {target_display} ====
{self.format_prompts_dict.get(target_format, '')}

==== QUY TẮC BẮT BUỘC ====
1. TUYỆT ĐỐI CHỈ DÙNG TIẾNG VIỆT. (Trường _en đã bị loại bỏ).
2. TRẢ VỀ JSON TUÂN THỦ CHÍNH XÁC SCHEMA của dạng "{target_format}" (Chú ý JSON escape \\\\).
3. MỌI CÔNG THỨC TOÁN/LÝ/HOÁ PHẢI NẰM TRONG CẶP DẤU `$`. (Ví dụ: `$H_2O$`, `$x^2 = 4$`).
   TUYỆT ĐỐI CẤM dùng `\\(` và `\\)` hoặc `\\[` và `\\]` cho công thức. CHỈ dùng `$...$`.
4. BẮT BUỘC chép lại chính xác "_id" và "dvkt" từ json gốc sang câu hỏi mới.
5. CÂU HỎI NHƯ THẾ NÀO THÌ VIẾT LẠI Y NHƯ VẬY (TỪNG CHỮ MỘT NẾU CÓ THỂ), CHỈ THAY ĐỔI CÁC CON SỐ THÀNH SỐ MỚI ĐỂ TẠO RA ĐÁP ÁN MỚI. KHÔNG SÁNG TẠO THÊM NGỮ CẢNH.
6. NỘI DUNG PHẢI NẰM TRONG PHẠM VI MÔN {detected_subject} CẤP THPT. CẤM VƯỢT CHƯƠNG TRÌNH.
7. SỐ MỚI PHẢI ĐẸP: Kết quả cuối cùng phải là số nguyên, phân số đơn giản, hoặc căn đơn giản.
   TUYỆT ĐỐI KHÔNG ĐƯỢC sinh số xấu (số thập phân vô hạn, phân số phức tạp) khiến bài toán không giải được đẹp.
   CẤM sửa đổi cấu trúc đề bài sau khi đã chọn số — nếu số mới không ra kết quả đẹp, HÃY CHỌN LẠI SỐ KHÁC.
8. LỜI GIẢI ("giai_thich") PHẢI XUỐNG DÒNG rõ ràng:
   - Mỗi bước giải PHẢI trên một dòng riêng (dùng ký tự \\n để xuống dòng).
   - TUYỆT ĐỐI KHÔNG viết toàn bộ lời giải trên một dòng liên tục.
   - Kết thúc mỗi bước bằng dấu chấm hoặc dấu chấm phẩy rồi xuống dòng.
9. YÊU CẦU SINH CHUẨN TƯƠNG TỰ: Cấu trúc câu từ, độ dài, sự chi tiết, cách trình bày của câu hỏi và lời giải mới PHẢI CHUẨN XÁC, TƯƠNG TỰ 100% với đề gốc. KHÔNG ĐƯỢC phép làm ngắn gọn đi hay tóm tắt lại. Mọi thứ phải chuẩn mực, rõ ràng.

==== HÌNH ẢNH ====
{image_instruction}

==== THÔNG TIN HÌNH ẢNH ĐỀ GỐC ====
{item_json.get('_image_metadata_info', 'Đề gốc KHÔNG có hình ảnh nhúng trong lời giải.')}

==== CÂU HỎI GỐC CẦN SAO CHÉP ====
`typeAnswer` (Loại đề gốc) là: {item_json.get('typeAnswer', 'Không rõ')}

```json
{json.dumps(item_json, ensure_ascii=False)}
```

NHẮC LẠI LẦN CUỐI: Output PHẢI là dạng "{target_format}" với "loai_de": "{target_format}".
Trả về ĐÚNG MỘT OBJECT JSON tuân thủ chính xác Schema của dạng "{target_format}".
"""

    def process_item(self, client, item, target_format, image_instruction=""):
        if self.is_cancelled:
            return None
            
        clean_item = deepcopy(item)
        
        # --- TRÍCH XUẤT METADATA HÌNH ẢNH TRƯỚC KHI XÓA BASE64 ---
        image_meta = extract_image_metadata(item)
        if image_meta:
            meta_str = f"Đề gốc có {len(image_meta)} hình ảnh nhúng trong lời giải/đề bài/gợi ý:\n"
            for i, desc in enumerate(image_meta, 1):
                meta_str += f"  {i}. {desc}\n"
            meta_str += "→ Câu clone BẮT BUỘC phải giữ lại ý tưởng hình ảnh tương tự.\n"
            meta_str += "→ NẾU đề bài có hình: đặt co_hinh=true trong 'hinh_anh' với mo_ta mô tả chính xác.\n"
            meta_str += "→ NẾU lời giải có hình/bảng biến thiên: đặt co_hinh=true trong 'hinh_anh_giai_thich' với mo_ta mô tả chi tiết.\n"
            meta_str += "→ NẾU gợi ý có hình: đặt co_hinh=true trong 'hinh_anh_goi_y' với mo_ta tương ứng.\n"
            clean_item['_image_metadata_info'] = meta_str
        else:
            clean_item['_image_metadata_info'] = 'Đề gốc KHÔNG có hình ảnh nhúng trong lời giải.'
        
        if "image" in clean_item and str(clean_item["image"]).startswith("data:"):
            clean_item["image"] = "[REMOVED_TO_SAVE_TOKENS]"
        
        # Xóa base64 images inline trong explain/content/goi_y để tiết kiệm tokens
        for field in ['explain', 'content', 'goi_y']:
            if field in clean_item and isinstance(clean_item[field], str):
                clean_item[field] = re.sub(
                    r'<img[^>]*src=["\']data:image[^"\'>]*["\'][^>]*>',
                    '[INLINE_IMAGE_REMOVED - see _image_metadata_info for description]',
                    clean_item[field], flags=re.IGNORECASE | re.DOTALL
                )
            
        if isinstance(clean_item.get("_id"), dict) and "$oid" in clean_item["_id"]:
            clean_item["_id"] = clean_item["_id"]["$oid"]
            
        prompt = self.build_final_prompt(clean_item, target_format, image_instruction=image_instruction)
        
        target_schema_dict = {
            "trac_nghiem_4_dap_an": schema_trac_nghiem,
            "dung_sai": schema_dung_sai,
            "tra_loi_ngan": schema_tra_loi_ngan,
            "tu_luan": schema_tu_luan
        }
        active_schema = target_schema_dict.get(target_format, schema_trac_nghiem)
        
        wrapper_schema = {
            "type": "OBJECT",
            "properties": {
                "loai_de": {
                    "type": "STRING",
                    "enum": [target_format]
                },
                "du_lieu": active_schema
            },
            "required": ["loai_de", "du_lieu"]
        }
        
        try:
            response_text = client.send_data_to_AI(
                prompt=prompt,
                temperature=0.1, # Clone chặt: gần như không sáng tạo, chỉ đổi số liệu
                response_schema=wrapper_schema
            )
            
            json_match = re.search(r'```json\n(.*?)\n```', response_text, re.DOTALL)
            if json_match:
                response_text = json_match.group(1)
                
            result_json = json.loads(response_text)
            
            # --- LOẠI BỎ HTML TAGS (VD: <u>, <ins>, <br />) ---
            result_json = strip_html_from_json(result_json)
            
            # --- POST-PROCESSING: Sửa format công thức + xuống dòng lời giải ---
            result_json = post_process_clone_json(result_json)
            
            result_json["loai_de"] = target_format
            if "du_lieu" in result_json:
                result_json["du_lieu"]["loai_de"] = target_format
            
            level_map = {
                "NB": "nhan_biet",
                "TH": "thong_hieu", 
                "VD": "van_dung",
                "VDC": "van_dung_cao"
            }
            mapped_level = level_map.get(item.get("level", "VD"), "van_dung")
            
            cau_hoi_arr = result_json.get("du_lieu", {}).get("cau_hoi", [])
            for ch in cau_hoi_arr:
                ch["_id"] = item.get("_id", "UNKNOWN_ID")
                ch["dvkt"] = item.get("dvkt", "UNKNOWN_DVKT")
                ch["muc_do"] = mapped_level
                
            # --- VALIDATION: Kiểm tra chất lượng clone ---
            self._validate_clone_quality(item, result_json)
                
            return result_json
            
        except json.JSONDecodeError:
            self.log_message.emit(f"❌ JSONDecodeError cho ID {clean_item.get('_id')}")
            return None
        except Exception as e:
            self.log_message.emit(f"❌ API Error ID {clean_item.get('_id')}: {str(e)}")
            return None

    def _validate_clone_quality(self, original_item, result_json):
        """Kiểm tra chất lượng clone, cảnh báo nếu AI tự sửa đề hoặc dùng số xấu."""
        orig_id = original_item.get("_id", "UNKNOWN")
        
        # Lấy toàn bộ text giải thích để check
        all_explanations = []
        cau_hoi_arr = result_json.get("du_lieu", {}).get("cau_hoi", [])
        for ch in cau_hoi_arr:
            all_explanations.append(str(ch.get("giai_thich", "")))
            
        full_text = " ".join(all_explanations).lower()
        
        # Kiểm tra pattern "sửa lại đề"
        bad_patterns = [
            "sửa lại đề", "sửa đề", "thay đổi đề", "chọn lại số", "sửa số liệu",
            "đổi lại đề", "phải sửa lại", "đề bài sai", "nghiệm xấu"
        ]
        
        for pattern in bad_patterns:
            if pattern in full_text:
                self.log_message.emit(f"⚠️ CẢNH BÁO ID {orig_id}: CÓ THỂ AI ĐÃ TỰ SỬA ĐỀ BÀI (tìm thấy cụm từ '{pattern}' trong lời giải) do sinh số xấu.")
                break

    def run(self):
        try:
            self.log_message.emit(f"Đang đọc file: {self.input_file}")
            with open(self.input_file, 'r', encoding='utf-8') as f:
                content = f.read()
                
            content = re.sub(r'ObjectId\("([0-9a-fA-F]{24})"\)', r'{"$oid": "\1"}', content)
            content = re.sub(r'NumberInt\((\d+)\)', r'\1', content)
            
            content = content.strip()
            
            # --- GỘP MẢNG NỐI TIẾP: ],\n{ → ,\n{ ---
            # Xử lý file chứa nhiều mảng JSON nối tiếp nhau (vd: [...],\n{...})
            content = re.sub(r'\]\s*,\s*\{', r',\n{', content)
            
            # Đảm bảo content là một mảng duy nhất
            content = content.strip().rstrip(',')
            if not content.startswith('['):
                content = '[\n' + content
            if not content.endswith(']'):
                content = content.rstrip(',') + '\n]'
                
            try:
                data = json.loads(content)
            except json.JSONDecodeError as e:
                self.log_message.emit(f"Lỗi parse JSON sau khi clean: {e}")
                self.process_finished.emit(False, f"Lỗi parse định dạng file: {e}")
                return
                
            if not isinstance(data, list):
                data = [data]
                
            total_items = len(data)
            if total_items == 0:
                self.process_finished.emit(False, "File JSON không có câu hỏi nào.")
                return

            creds = get_vertex_ai_credentials()
            project_id = os.getenv("PROJECT_ID")
            
            model_name = "gemini-2.5-pro" 
            
            self.log_message.emit(f"Đang khởi tạo model {model_name}...")
            client = VertexClient(project_id, creds, model_name=model_name)
            
            generated_results = []
            completed = 0

            type_answer_map = {
                "TN": "trac_nghiem_4_dap_an",
                "DS": "dung_sai",
                "TLN": "tra_loi_ngan",
                "TL": "tu_luan"
            }
            
            # --- THỐNG KÊ SỐ CÂU CÓ HÌNH TRONG FILE GỐC ---
            img_count = sum(
                1 for item in data
                if item.get("image") and
                str(item.get("image", "")) not in ["", "[REMOVED_TO_SAVE_TOKENS]"] and
                not str(item.get("image", "")).startswith("data:")
            )
            self.log_message.emit(f"📊 Thống kê: {img_count}/{total_items} câu gốc có hình ảnh.")
            
            tasks = []
            for item in data:
                src = type_answer_map.get(item.get("typeAnswer", ""), "trac_nghiem_4_dap_an")
                tasks.append((item, src))
            
            # === TÍNH QUOTA HÌNH ẢNH ===
            image_count = round(total_items * self.image_pct / 100)
            if image_count > 0:
                image_indices = set(random.sample(range(total_items), min(image_count, total_items)))
            else:
                image_indices = set()
            self.log_message.emit(f"🖼️ Quota hình ảnh: {len(image_indices)}/{total_items} câu ({self.image_pct}%)")
            
            # Gán image_instruction cho từng task
            IMAGE_YES = """BẮT BUỘC PHẢI SINH HÌNH ẢNH cho câu hỏi này nếu đề gốc có hình.
→ Đặt "co_hinh": true cho các property tương ứng (hinh_anh, hinh_anh_giai_thich, hinh_anh_goi_y) và "loai": "tu_mo_ta"
→ "mo_ta": Mô tả chi tiết hình ảnh bằng TIẾNG ANH (diagram, graph, table...). TUYỆT ĐỐI KHÔNG ĐỂ TRỐNG.
→ VÍ DỤ: "A bar chart showing the comparison of rainfall in four seasons" hoặc "A variation table of a quadratic function".
→ NẾU đề gốc có hình ở lời giải, PHẢI sinh hinh_anh_giai_thich."""
            IMAGE_NO = """TUYỆT ĐỐI KHÔNG ĐƯỢC SINH HÌNH ẢNH cho câu hỏi này.
→ "co_hinh": false cho mọi trường hình ảnh.
→ NGHIÊM CẤM đặt co_hinh = true."""
            
            task_with_img = []
            for i, (task_item, task_format) in enumerate(tasks):
                img_instr = IMAGE_YES if i in image_indices else IMAGE_NO
                task_with_img.append((task_item, task_format, img_instr))
            
            self.log_message.emit(f"Bắt đầu xử lý {total_items} câu hỏi bằng đa luồng (temperature=0.1 - Clone chặt).")
            
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = {executor.submit(self.process_item, client, task_item, task_format, img_instr): (task_item, task_format) for task_item, task_format, img_instr in task_with_img}
                for future in as_completed(futures):
                    if self.is_cancelled:
                        executor.shutdown(wait=False, cancel_futures=True)
                        self.process_finished.emit(False, "Đã hủy tiến trình.")
                        return
                        
                    res = future.result()
                    if res:
                        generated_results.append(res)
                    completed += 1
                    self.progress_updated.emit(completed, total_items)
                    
            if not generated_results:
                self.process_finished.emit(False, "Không sinh được câu hỏi nào thành công.")
                return
                
            self.log_message.emit("Hoàn thành sinh API. Bắt đầu đánh số lại STT để xuất DOCX...")
            
            current_stt = 1
            for res_item in generated_results:
                du_lieu = res_item.get("du_lieu", {})
                cau_hoi_arr = du_lieu.get("cau_hoi", [])
                for ch in cau_hoi_arr:
                    ch["stt"] = current_stt
                    current_stt += 1
            
            base_name = os.path.splitext(os.path.basename(self.input_file))[0]
            if not os.path.exists(self.output_dir):
                os.makedirs(self.output_dir, exist_ok=True)
                
            json_path = os.path.join(self.output_dir, f"{base_name}_cloned.json")
            docx_path = os.path.join(self.output_dir, f"{base_name}_cloned.docx")
            
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(generated_results, f, ensure_ascii=False, indent=4)
            self.log_message.emit(f"✅ Đã lưu JSON chuẩn: {json_path}")
            
            # --- KIỂM TRA PANDOC TRƯỚC KHI RENDER DOCX ---
            pandoc_path = find_pandoc_executable()
            if pandoc_path:
                self.log_message.emit(f"✅ Pandoc tìm thấy: {pandoc_path} — Công thức toán sẽ render OMML.")
            else:
                self.log_message.emit(" Không tìm thấy Pandoc! Công thức toán sẽ hiển thị dạng text thô [$...$].")
            
            doc = Document()
            renderer = DynamicDocxRenderer(doc)
            for item in generated_results:
                loai_de = item.get("loai_de")
                du_lieu = item.get("du_lieu", {})
                cau_hoi_arr = du_lieu.get("cau_hoi", [])
                for cau_hoi in cau_hoi_arr:
                    try:
                        if loai_de == "dung_sai": renderer.render_question_dung_sai(cau_hoi)
                        elif loai_de == "tra_loi_ngan": renderer.render_question_tra_loi_ngan(cau_hoi)
                        elif loai_de == "tu_luan": renderer.render_question_tu_luan(cau_hoi)
                        else: renderer.render_question_trac_nghiem(cau_hoi)
                    except Exception as e:
                        self.log_message.emit(f" Lỗi kết xuất hình/text DOCX câu {cau_hoi.get('_id')}: {e}")
                        
            doc.save(docx_path)
            self.log_message.emit(f"✅ Đã lưu DOCX chuẩn: {docx_path}")
            
            self.process_finished.emit(True, "Vận hành xuất sắc 2 file JSON và DOCX thành công!")
            
        except Exception as e:
            self.process_finished.emit(False, f"Crash hệ thống ngoại lệ: {str(e)}")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🔥 Clone Câu Hỏi (Chỉ thay số liệu, đối tượng) - Gemini-2.5-Pro")
        self.resize(1000, 650)
        self.worker = None
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        file_group = QGroupBox("1. Thiết lập Thư Mục Tập Tin")
        f_layout = QVBoxLayout()
        
        h_in = QHBoxLayout()
        self.txt_input = QLineEdit()
        self.txt_input.setPlaceholderText("Chọn file JSON gốc (vd: VATLITHPT2_1_1_1.json)...")
        btn_in = QPushButton("Browse JSON...")
        btn_in.clicked.connect(self.browse_input)
        h_in.addWidget(QLabel("File JSON Gốc:"))
        h_in.addWidget(self.txt_input)
        h_in.addWidget(btn_in)
        
        h_out = QHBoxLayout()
        self.txt_output = QLineEdit()
        default_out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated_clones")
        self.txt_output.setText(default_out)
        btn_out = QPushButton("Browse Dir...")
        btn_out.clicked.connect(self.browse_output)
        h_out.addWidget(QLabel("Lưu Kết Quả Vào:"))
        h_out.addWidget(self.txt_output)
        h_out.addWidget(btn_out)
        
        f_layout.addLayout(h_in)
        f_layout.addLayout(h_out)
        file_group.setLayout(f_layout)
        
        prompt_group = QGroupBox("2. Cấu hình AI Prompt (Chọn từ File TXT để giữ lại cấu trúc mong muốn)")
        p_layout = QVBoxLayout()
        
        def create_prompt_selector(label_text, placeholder):
            h_layout = QHBoxLayout()
            txt_path = QLineEdit()
            txt_path.setPlaceholderText(placeholder)
            btn_browse = QPushButton("Chọn File...")
            btn_browse.clicked.connect(lambda: self.browse_txt_file(txt_path))
            h_layout.addWidget(QLabel(label_text))
            h_layout.addWidget(txt_path)
            h_layout.addWidget(btn_browse)
            return h_layout, txt_path

        self.layout_tn, self.txt_prompt_tn = create_prompt_selector("Prompt Trắc Nghiệm:", "File promptTracNghiem.txt...")
        self.layout_ds, self.txt_prompt_ds = create_prompt_selector("Prompt Đúng/Sai:", "File promptDungSai.txt...")
        self.layout_tl, self.txt_prompt_tl = create_prompt_selector("Prompt Trả Lời Ngắn:", "File promptTraLoiNgan.txt...")
        self.layout_tuluan, self.txt_prompt_tuluan = create_prompt_selector("Prompt Tự Luận:", "File promptTuLuan.txt...")
        self.layout_eng, self.txt_prompt_eng = create_prompt_selector("🇬🇧 Prompt Tiếng Anh:", "File promptCloneTiengAnh.txt...")
        
        p_layout.addWidget(QLabel("<i>(Bắt buộc chỉ định file Prompt cụ thể của 4 định dạng bài + Prompt Tiếng Anh để AI học cấu trúc schema)</i>"))
        p_layout.addLayout(self.layout_tn)
        p_layout.addLayout(self.layout_ds)
        p_layout.addLayout(self.layout_tl)
        p_layout.addLayout(self.layout_tuluan)
        p_layout.addLayout(self.layout_eng)
        
        # Default prompt paths if not manually selected
        base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Prompt sinh câu hỏi TIẾNG VIỆT")
        self.txt_prompt_tn.setText(os.path.join(base_dir, "promptCloneTracNghiem.txt"))
        self.txt_prompt_ds.setText(os.path.join(base_dir, "promptCloneDungSai.txt"))
        self.txt_prompt_tl.setText(os.path.join(base_dir, "promptCloneTraLoiNgan.txt"))
        self.txt_prompt_tuluan.setText(os.path.join(base_dir, "promptCloneTuLuan.txt"))
        self.txt_prompt_eng.setText(os.path.join(base_dir, "promptCloneTiengAnh.txt"))
        
        prompt_group.setLayout(p_layout)
        
        # --- IMAGE QUOTA ---
        img_group = QGroupBox("3. Thiết Lập Tỷ Lệ Hình Ảnh")
        img_layout = QHBoxLayout()
        self.spin_image = QSpinBox()
        self.spin_image.setRange(0, 100)
        self.spin_image.setValue(10)
        self.spin_image.setSuffix("%")
        img_layout.addWidget(QLabel("🖼️ % Câu hỏi có hình ảnh:"))
        img_layout.addWidget(self.spin_image)
        img_layout.addStretch()
        img_group.setLayout(img_layout)
        
        action_layout = QHBoxLayout()
        self.btn_start = QPushButton("🚀 Bắt Đầu Tiến Trình AI (Clone)")
        self.btn_start.setMinimumHeight(40)
        self.btn_start.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold; font-size: 14px;")
        self.btn_start.clicked.connect(self.start_conversion)
        
        self.btn_stop = QPushButton("🛑 Hủy")
        self.btn_stop.setMinimumHeight(40)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet("background-color: #c62828; color: white; font-weight: bold;")
        self.btn_stop.clicked.connect(self.stop_conversion)
        
        action_layout.addWidget(self.btn_start)
        action_layout.addWidget(self.btn_stop)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setStyleSheet("background-color: #1e1e1e; color: #a5d6ff; font-family: Consolas;")
        
        main_layout.addWidget(file_group)
        main_layout.addWidget(prompt_group)
        main_layout.addWidget(img_group)
        main_layout.addLayout(action_layout)
        main_layout.addWidget(self.progress_bar)
        main_layout.addWidget(QLabel("<b>Log Console:</b>"))
        main_layout.addWidget(self.log_console)
        
    def browse_input(self):
        file, _ = QFileDialog.getOpenFileName(self, "Chọn file JSON câu hỏi", "", "JSON Files (*.json);;All Files (*)")
        if file:
            self.txt_input.setText(file)
            
    def browse_output(self):
        directory = QFileDialog.getExistingDirectory(self, "Chọn thư mục xuất DOCX và JSON")
        if directory:
            self.txt_output.setText(directory)

    def browse_txt_file(self, line_edit_widget):
        file, _ = QFileDialog.getOpenFileName(self, "Chọn file Prompt", "", "Text Files (*.txt);;Mọi tập tin (*.*)")
        if file:
            line_edit_widget.setText(file)

    def print_log(self, text):
        self.log_console.append(text)

    def read_prompt_file(self, filepath):
        if not filepath or not os.path.exists(filepath):
            return ""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                filename = os.path.basename(filepath)
                return f"=== Nội dung file {filename} ===\n" + f.read() + "\n"
        except Exception as e:
            return f"=== Lỗi đọc file {filepath}: {e} ===\n"

    def start_conversion(self):
        input_file = self.txt_input.text().strip()
        output_dir = self.txt_output.text().strip()
        
        if not input_file or not os.path.isfile(input_file):
            QMessageBox.warning(self, "Lỗi Input", "Vui lòng chọn một file JSON nguồn khả dụng.")
            return

        format_prompts_dict = {
            "trac_nghiem_4_dap_an": self.read_prompt_file(self.txt_prompt_tn.text().strip()),
            "dung_sai": self.read_prompt_file(self.txt_prompt_ds.text().strip()),
            "tra_loi_ngan": self.read_prompt_file(self.txt_prompt_tl.text().strip()),
            "tu_luan": self.read_prompt_file(self.txt_prompt_tuluan.text().strip()),
            "tieng_anh": self.read_prompt_file(self.txt_prompt_eng.text().strip()),
        }
        
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress_bar.setValue(0)
        self.log_console.clear()
        self.print_log("Đang khởi động hệ thống Clone API...")

        self.worker = ConversionWorker(
            input_file=input_file,
            output_dir=output_dir,
            format_prompts_dict=format_prompts_dict,
            image_pct=self.spin_image.value()
        )
        self.worker.progress_updated.connect(self.update_progress)
        self.worker.log_message.connect(self.print_log)
        self.worker.process_finished.connect(self.on_finished)
        self.worker.start()

    def update_progress(self, current, total):
        pct = int((current / total) * 100)
        self.progress_bar.setValue(pct)
        self.progress_bar.setFormat(f"{current}/{total} Khối ({pct}%)")

    def stop_conversion(self):
        if self.worker:
            self.worker.is_cancelled = True
            self.print_log(" Gửi tín hiệu hủy...")

    def on_finished(self, success, message):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_bar.setValue(100 if success else 0)
        self.print_log(f"\n--- KẾT THÚC ---")
        self.print_log(message)
        if success:
            QMessageBox.information(self, "Hoàn Tất", message)
        else:
            QMessageBox.critical(self, "Lỗi Nghiêm Trọng", message)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())