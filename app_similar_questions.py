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
from genques.response2docxTN import DynamicDocxRenderer
from docx import Document


# ---------------------------------------------------------
# HTML TAG STRIPPING
# ---------------------------------------------------------
def strip_html_tags(text):
    """Chuyển đổi HTML tags thông minh: <u>/<ins> → [text], xóa các tag còn lại."""
    if not isinstance(text, str):
        return text
    # Chuyển <u>text</u> và <ins>text</ins> thành [text] (giữ nghĩa cho câu tìm lỗi sai)
    text = re.sub(r'<u>(.*?)</u>', r'[\1]', text, flags=re.IGNORECASE|re.DOTALL)
    text = re.sub(r'<ins>(.*?)</ins>', r'[\1]', text, flags=re.IGNORECASE|re.DOTALL)
    # Xóa các tag HTML còn lại (VD: <br>, <br/>, <b>, <i>...)
    text = re.sub(r'<[^>]+>', '', text)
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

# ---------------------------------------------------------
# SCHEMA DEFINITIONS
# ---------------------------------------------------------
SUPER_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "loai_de": {
            "type": "STRING", 
            "enum": ["dung_sai", "tra_loi_ngan", "tu_luan", "trac_nghiem_4_dap_an"],
            "description": "Loại định dạng BẮT BUỘC PHẢI KHÁC với định dạng gốc của câu hỏi đưa vào."
        },
        "du_lieu": {
            "anyOf": [
                schema_dung_sai,
                schema_tra_loi_ngan,
                schema_tu_luan,
                schema_trac_nghiem
            ]
        }
    },
    "required": ["loai_de", "du_lieu"]
}

# ---------------------------------------------------------
# WORKER THREAD FOR API PROCESSING
# ---------------------------------------------------------
class ConversionWorker(QThread):
    progress_updated = pyqtSignal(int, int) # Current, Total
    log_message = pyqtSignal(str)
    process_finished = pyqtSignal(bool, str) # Success, Message

    def __init__(self, input_file, output_dir, global_prompt, format_prompts_dict, allocations, image_pct=10):
        super().__init__()
        self.input_file = input_file
        self.output_dir = output_dir
        self.global_prompt = global_prompt         # The main text box instruction
        self.format_prompts_dict = format_prompts_dict  # Dict: {format_name: prompt_text}
        self.allocations = allocations             # dict of target limits
        self.image_pct = image_pct                 # % câu hỏi có hình ảnh (0-100)
        self.is_cancelled = False

    def build_final_prompt(self, item_json, target_format, image_instruction=""):
        # Tên hiển thị tiếng Việt của target format
        format_display = {
            "trac_nghiem_4_dap_an": "TRẮC NGHIỆM 4 ĐÁP ÁN (A, B, C, D)",
            "dung_sai": "ĐÚNG/SAI (4 mệnh đề a, b, c, d)",
            "tra_loi_ngan": "TRẢ LỜI NGẮN (Đáp án là MỘT CON SỐ duy nhất)",
            "tu_luan": "TỰ LUẬN (Bài toán giải chi tiết, đáp án cụ thể)"
        }
        target_display = format_display.get(target_format, target_format)

        return f"""Bạn là một Chuyên gia Giáo dục & AI. Nhiệm vụ TUYỆT ĐỐI BẮT BUỘC của bạn là:
1. Nhận vào MỘT câu hỏi (JSON).
2. CHUYỂN ĐỔI nó sang DẠNG MỚI HOÀN TOÀN KHÁC: "{target_display}".
3. Giữ nguyên KIẾN THỨC CỐT LÕI nhưng thay đổi BỐI CẢNH, cách hỏi, và cấu trúc.

╔══════════════════════════════════════════════════════════════╗
   LỆNH CƯỠNG CHẾ ĐỊNH DẠNG (FORMAT ENFORCEMENT)       
                                                              
  BẠN BẮT BUỘC PHẢI XUẤT RA ĐÚNG DẠNG: {target_format:<30s}
                                                              
  → Trường "loai_de" trong JSON output PHẢI = "{target_format}"
  → Cấu trúc "du_lieu" PHẢI tuân thủ SCHEMA của dạng này.    
  → Nếu bạn xuất ra dạng KHÁC → KẾT QUẢ BỊ LOẠI BỎ.        
                                                              
  Trong phần QUY ĐỊNH ĐỊNH DẠNG bên dưới, có nhiều dạng bài. 
  BẠN CHỈ ĐƯỢC ĐỌC VÀ ÁP DỤNG DUY NHẤT DẠNG:               
  "{target_format}"                             
  BỎ QUA HOÀN TOÀN các dạng khác.                            


==== PROMPT HƯỚNG DẪN TỪ NGƯỜI DÙNG ====
{self.global_prompt}

==== QUY ĐỊNH CHI TIẾT CHO DẠNG: {target_display} ====
{self.format_prompts_dict.get(target_format, '')}

==== QUY TẮC BẮT BUỘC ====
1. TUYỆT ĐỐI CHỈ DÙNG TIẾNG VIỆT. (Trường _en đã bị loại bỏ).
2. TRẢ VỀ JSON TUÂN THỦ CHÍNH XÁC SCHEMA của dạng "{target_format}" (Chú ý JSON escape \\\\).
3. MỌI CÔNG THỨC TOÁN/LÝ/HOÁ PHẢI NẰM TRONG CẶP DẤU `$`. (Ví dụ: `$H_2O$`, `$x^2 = 4$`).
4. BẮT BUỘC chép lại chính xác \"_id\" và \"dvkt\" từ json gốc sang câu hỏi mới.

==== HÌNH ẢNH ====
{image_instruction}

==== CÂU HỎI GỐC CẦN CHUYỂN ĐỔI ====
`typeAnswer` (Loại đề gốc) là: {item_json.get('typeAnswer', 'Không rõ')}

 CẢNH BÁO: Dạng gốc là "{item_json.get('typeAnswer', 'Không rõ')}". 
BẠN TUYỆT ĐỐI KHÔNG ĐƯỢC GIỮ NGUYÊN DẠNG GỐC. 
BẠN BẮT BUỘC PHẢI CHUYỂN SANG DẠNG: {target_display}.

```json
{json.dumps(item_json, ensure_ascii=False)}
```

Hãy suy nghĩ cẩn thận, ĐỔI BỐI CẢNH hoặc LẬT NGƯỢC VẤN ĐỀ để tạo sự mới mẻ.
NHẮC LẠI LẦN CUỐI: Output PHẢI là dạng "{target_format}" với "loai_de": "{target_format}".
Trả về ĐÚNG MỘT OBJECT JSON tuân thủ chính xác Schema của dạng "{target_format}".
"""

    def process_item(self, client, item, target_format, image_instruction=""):
        if self.is_cancelled:
            return None
            
        clean_item = deepcopy(item)
        if "image" in clean_item and str(clean_item["image"]).startswith("data:"):
            clean_item["image"] = "[REMOVED_TO_SAVE_TOKENS]"
            
        if isinstance(clean_item.get("_id"), dict) and "$oid" in clean_item["_id"]:
            clean_item["_id"] = clean_item["_id"]["$oid"]
            
        prompt = self.build_final_prompt(clean_item, target_format, image_instruction=image_instruction)
        
        # Chọn đúng 1 schema duy nhất để nhồi vào Vertex
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
                    "enum": [target_format]  # CƯỠNG CHẾ: Chỉ cho phép đúng 1 giá trị
                },
                "du_lieu": active_schema
            },
            "required": ["loai_de", "du_lieu"]
        }
        
        try:
            response_text = client.send_data_to_AI(
                prompt=prompt,
                temperature=0.1,
                response_schema=wrapper_schema
            )
            
            json_match = re.search(r'```json\n(.*?)\n```', response_text, re.DOTALL)
            if json_match:
                response_text = json_match.group(1)
                
            result_json = json.loads(response_text)
            
            # --- LOẠI BỎ HTML TAGS (VD: <u>, <ins>, <br />) ---
            result_json = strip_html_from_json(result_json)
            
            # --- CƯỠNG CHẾ loai_de = target_format (BẤT KỂ AI TRẢ VỀ GÌ) ---
            ai_loai_de = result_json.get("loai_de", "?")
            ai_inner_loai_de = result_json.get("du_lieu", {}).get("loai_de", "?")
            result_json["loai_de"] = target_format
            if "du_lieu" in result_json:
                result_json["du_lieu"]["loai_de"] = target_format
            
            if ai_loai_de != target_format or ai_inner_loai_de != target_format:
                self.log_message.emit(f"⚡ Override loai_de: AI trả '{ai_loai_de}'/'{ai_inner_loai_de}' → '{target_format}'")
            
            # --- CƯỠNG CHẾ GHI ĐÈ METADATA ---
            # Dịch level -> muc_do
            level_map = {
                "NB": "nhan_biet",
                "TH": "thong_hieu", 
                "VD": "van_dung",
                "VDC": "van_dung_cao"
            }
            mapped_level = level_map.get(item.get("level", "VD"), "van_dung")
            
            # Quét tìm mảng cau_hoi để đè
            cau_hoi_arr = result_json.get("du_lieu", {}).get("cau_hoi", [])
            for ch in cau_hoi_arr:
                ch["_id"] = item.get("_id", "UNKNOWN_ID")
                ch["dvkt"] = item.get("dvkt", "UNKNOWN_DVKT")
                ch["muc_do"] = mapped_level
                
            return result_json
            
        except json.JSONDecodeError:
            self.log_message.emit(f"❌ JSONDecodeError cho ID {clean_item.get('_id')}")
            return None
        except Exception as e:
            self.log_message.emit(f"❌ API Error ID {clean_item.get('_id')}: {str(e)}")
            return None

    def run(self):
        try:
            self.log_message.emit(f"Đang đọc file: {self.input_file}")
            with open(self.input_file, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Chuẩn hoá các trường hợp dữ liệu lỗi từ CSDL cũ
            content = re.sub(r'ObjectId\("([0-9a-fA-F]{24})"\)', r'{"$oid": "\1"}', content)
            content = re.sub(r'NumberInt\((\d+)\)', r'\1', content)
            
            # Làm sạch dấu phẩy thừa ở cuối file trước khi load
            content = content.strip()
            if content.endswith(','):
                content = content[:-1]
                
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                # Fallback: Nếu file chứa mảng JSON bị thiếu ngặc vuông [ ] bao ngoài (như VATLITHPT2_1_1.JSON)
                self.log_message.emit("Phát hiện định dạng JSON không mảng, đang tự động bọc lại...")
                try:
                    content_wrapped = "[\n" + content + "\n]"
                    data = json.loads(content_wrapped)
                except Exception as e:
                    self.process_finished.emit(False, f"Lỗi parse định dạng file ngầm nội bộ: {e}")
                    return
                
            if not isinstance(data, list):
                data = [data]
                
            total_items = len(data)
            if total_items == 0:
                self.process_finished.emit(False, "File JSON không có câu hỏi nào.")
                return

            creds = get_vertex_ai_credentials()
            project_id = os.getenv("PROJECT_ID")
            
            # --- MANDATORY GEMINI 3 PRO PREVIEW ---
            model_name = "gemini-2.5-pro" 
            
            self.log_message.emit(f"Đang khởi tạo model {model_name}...")
            client = VertexClient(project_id, creds, model_name=model_name)
            
            generated_results = []
            completed = 0

            # === PHÂN BỔ: phân bổ toàn cục theo trọng số ===
            type_answer_map = {
                "TN": "trac_nghiem_4_dap_an",
                "DS": "dung_sai",
                "TLN": "tra_loi_ngan",
                "TL": "tu_luan"
            }
            format_weights = {
                "trac_nghiem_4_dap_an": self.allocations.get("tn", 0),
                "dung_sai": self.allocations.get("ds", 0),
                "tra_loi_ngan": self.allocations.get("tln", 0),
                "tu_luan": self.allocations.get("tl", 0)
            }
            all_formats = list(format_weights.keys())
            
            # Nhóm câu hỏi theo typeAnswer
            from collections import defaultdict
            groups = defaultdict(list)
            for i, item in enumerate(data):
                src = type_answer_map.get(item.get("typeAnswer", ""), "trac_nghiem_4_dap_an")
                groups[src].append((i, item))
            
            # === PHÂN BỔ TOÀN CỤC: Tính quota cho mỗi dạng theo trọng số ===
            # Cho phép chuyển cùng dạng (VD: TN → TN) để trọng số cao = output nhiều
            total_w = sum(format_weights.values())
            if total_w == 0:
                total_w = len(all_formats)
                format_weights = {f: 1 for f in all_formats}
            
            # Tính quota toàn cục cho mỗi dạng
            quota = {}
            assigned_total = 0
            fmt_list = list(format_weights.keys())
            for j, fmt in enumerate(fmt_list):
                if j == len(fmt_list) - 1:
                    quota[fmt] = total_items - assigned_total
                else:
                    quota[fmt] = round((format_weights[fmt] / total_w) * total_items)
                assigned_total += quota[fmt]
            
            # Gán target cho từng câu hỏi
            tasks = [None] * total_items
            # remaining_quota theo dõi số slot còn lại cho mỗi dạng
            remaining_quota = dict(quota)
            
            for source_format, items_in_group in groups.items():
                for idx, item in items_in_group:
                    # Tìm dạng có nhiều slot nhất
                    # Ưu tiên: dạng có remaining_quota lớn nhất
                    best_fmt = None
                    best_count = -1
                    for fmt in all_formats:
                        if remaining_quota.get(fmt, 0) > best_count:
                            best_count = remaining_quota[fmt]
                            best_fmt = fmt
                    
                    if best_fmt is not None and best_count > 0:
                        tasks[idx] = (item, best_fmt)
                        remaining_quota[best_fmt] -= 1
                    else:
                        # Fallback: gán dạng đầu tiên còn slot
                        fallback = all_formats[0]
                        for fmt in all_formats:
                            if remaining_quota.get(fmt, 0) > 0:
                                fallback = fmt
                                break
                        tasks[idx] = (item, fallback)
                        remaining_quota[fallback] = remaining_quota.get(fallback, 0) - 1
            
            # Log
            fc = {}
            for _, f in tasks:
                fc[f] = fc.get(f, 0) + 1
            self.log_message.emit(f"📊 Phân bổ (loại dạng gốc, chia trọng số): {fc}")
            
            # === TÍNH QUOTA HÌNH ẢNH ===
            image_count = round(total_items * self.image_pct / 100)
            if image_count > 0:
                image_indices = set(random.sample(range(total_items), min(image_count, total_items)))
            else:
                image_indices = set()
            self.log_message.emit(f"🖼️ Quota hình ảnh: {len(image_indices)}/{total_items} câu ({self.image_pct}%)")
            
            # Gán image_instruction cho từng task
            IMAGE_YES = """BẮT BUỘC PHẢI SINH HÌNH ẢNH cho câu hỏi này.
→ "co_hinh": true, "loai": "tu_mo_ta"
→ "mo_ta": Mô tả chi tiết hình ảnh bằng TIẾNG VIỆT (sơ đồ, đồ thị, mạch điện, cấu trúc...). TUYỆT ĐỐI KHÔNG ĐỂ TRỐNG."""
            IMAGE_NO = """TUYỆT ĐỐI KHÔNG ĐƯỢC SINH HÌNH ẢNH cho câu hỏi này.
→ "co_hinh": false, "mo_ta": ""
→ NGHIÊM CẤM đặt co_hinh = true."""
            
            task_with_img = []
            for i, (task_item, task_format) in enumerate(tasks):
                img_instr = IMAGE_YES if i in image_indices else IMAGE_NO
                task_with_img.append((task_item, task_format, img_instr))
            
            self.log_message.emit(f"Bắt đầu xử lý {total_items} câu hỏi. Đa luồng: 3 workers.")
            
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
            
            # --- RENUMBER STT SEQUENTIALLY ---
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
                
            json_path = os.path.join(self.output_dir, f"{base_name}_converted.json")
            docx_path = os.path.join(self.output_dir, f"{base_name}_converted.docx")
            
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(generated_results, f, ensure_ascii=False, indent=4)
            self.log_message.emit(f"✅ Đã lưu JSON chuẩn: {json_path}")
            
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
            
            self.process_finished.emit(True, "Đã hoàn thành 2 file JSON và DOCX thành công!")
            
        except Exception as e:
            self.process_finished.emit(False, f"Crash hệ thống ngoại lệ: {str(e)}")

# ---------------------------------------------------------
# PYQT5 UI DEFINITION
# ---------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🔥 Sinh Câu Hỏi Tương Tự Bằng Vertex (Gemini-2.5-Pro)")
        self.resize(1000, 750)
        self.worker = None
        
        # UI Elements
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # --- TOP: FILES ---
        file_group = QGroupBox("1. Thiết lập Thư Mục Tập Tin")
        f_layout = QVBoxLayout()
        
        # Input JSON
        h_in = QHBoxLayout()
        self.txt_input = QLineEdit()
        self.txt_input.setPlaceholderText("Chọn file JSON gốc (vd: VATLITHPT2_1_1_1.json)...")
        btn_in = QPushButton("Browse JSON...")
        btn_in.clicked.connect(self.browse_input)
        h_in.addWidget(QLabel("File JSON Gốc:"))
        h_in.addWidget(self.txt_input)
        h_in.addWidget(btn_in)
        
        # Output DIR
        h_out = QHBoxLayout()
        self.txt_output = QLineEdit()
        default_out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated_similar")
        self.txt_output.setText(default_out)
        btn_out = QPushButton("Browse Dir...")
        btn_out.clicked.connect(self.browse_output)
        h_out.addWidget(QLabel("Lưu Kết Quả Vào:"))
        h_out.addWidget(self.txt_output)
        h_out.addWidget(btn_out)
        
        f_layout.addLayout(h_in)
        f_layout.addLayout(h_out)
        file_group.setLayout(f_layout)
        
        # --- MIDDLE: PROMPTS ---
        prompt_group = QGroupBox("2. Cấu hình AI Prompt (Chọn từ File TXT)")
        p_layout = QVBoxLayout()
        
        # Helper function for adding file selectors
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

        self.layout_global, self.txt_global_prompt = create_prompt_selector("Prompt Khởi Tạo (Yêu cầu sinh):", "File chứa lệnh mô tả sinh câu hỏi tương tự...")
        self.layout_tn, self.txt_prompt_tn = create_prompt_selector("Prompt Trắc Nghiệm:", "File promptTracNghiem.txt...")
        self.layout_ds, self.txt_prompt_ds = create_prompt_selector("Prompt Đúng/Sai:", "File promptDungSai.txt...")
        self.layout_tl, self.txt_prompt_tl = create_prompt_selector("Prompt Trả Lời Ngắn:", "File promptTraLoiNgan.txt...")
        self.layout_tuluan, self.txt_prompt_tuluan = create_prompt_selector("Prompt Tự Luận:", "File promptTuLuan.txt...")
        
        p_layout.addLayout(self.layout_global)
        p_layout.addWidget(QLabel("<i>(Bắt buộc chỉ định file Prompt cụ thể của 4 định dạng bài để AI học cấu trúc)</i>"))
        p_layout.addLayout(self.layout_tn)
        p_layout.addLayout(self.layout_ds)
        p_layout.addLayout(self.layout_tl)
        p_layout.addLayout(self.layout_tuluan)
        prompt_group.setLayout(p_layout)
        # --- MIDDLE 2: TARGET ALLOCATION (SỐ LƯỢNG) ---
        alloc_group = QGroupBox("3. Thiết Lập Tỷ Lệ Dạng Bài Đầu Ra (Theo % hoặc tỷ số)")
        a_layout = QHBoxLayout()
        
        self.spin_tn = QSpinBox()
        self.spin_tn.setRange(0, 100)
        self.spin_tn.setValue(25)
        self.spin_ds = QSpinBox()
        self.spin_ds.setRange(0, 100)
        self.spin_ds.setValue(25)
        self.spin_tln = QSpinBox()
        self.spin_tln.setRange(0, 100)
        self.spin_tln.setValue(25)
        self.spin_tl = QSpinBox()
        self.spin_tl.setRange(0, 100)
        self.spin_tl.setValue(25)
        
        self.spin_image = QSpinBox()
        self.spin_image.setRange(0, 100)
        self.spin_image.setValue(10)
        self.spin_image.setSuffix("%")
        
        a_layout.addWidget(QLabel("Trắc nghiệm:"))
        a_layout.addWidget(self.spin_tn)
        a_layout.addWidget(QLabel("Đúng/Sai:"))
        a_layout.addWidget(self.spin_ds)
        a_layout.addWidget(QLabel("Trả Lời Ngắn:"))
        a_layout.addWidget(self.spin_tln)
        a_layout.addWidget(QLabel("Tự Luận:"))
        a_layout.addWidget(self.spin_tl)
        a_layout.addWidget(QLabel("🖼️ Hình ảnh:"))
        a_layout.addWidget(self.spin_image)
        alloc_group.setLayout(a_layout)
        
        # --- BOTTOM: ACTIONS & LOGS ---
        action_layout = QHBoxLayout()
        self.btn_start = QPushButton("🚀 Bắt Đầu Tiến Trình AI")
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
        
        # Assembly
        main_layout.addWidget(file_group)
        main_layout.addWidget(prompt_group)
        main_layout.addWidget(alloc_group)
        main_layout.addLayout(action_layout)
        main_layout.addWidget(self.progress_bar)
        main_layout.addWidget(QLabel("<b>Bảng Theo Dõi Khai Thác (Log Console):</b>"))
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

        # Load file prompts
        global_prompt = self.read_prompt_file(self.txt_global_prompt.text().strip())
        if not global_prompt.strip():
            QMessageBox.warning(self, "Lỗi Prompt", "Bạn chưa chọn file Giới thiệu/Yêu cầu (Prompt Khởi Tạo)!")
            return

        format_prompts_dict = {
            "trac_nghiem_4_dap_an": self.read_prompt_file(self.txt_prompt_tn.text().strip()),
            "dung_sai": self.read_prompt_file(self.txt_prompt_ds.text().strip()),
            "tra_loi_ngan": self.read_prompt_file(self.txt_prompt_tl.text().strip()),
            "tu_luan": self.read_prompt_file(self.txt_prompt_tuluan.text().strip()),
        }
        
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress_bar.setValue(0)
        self.log_console.clear()
        self.print_log("Đang khởi động hệ thống Crawler API...")

        allocations = {
            "tn": self.spin_tn.value(),
            "ds": self.spin_ds.value(),
            "tln": self.spin_tln.value(),
            "tl": self.spin_tl.value()
        }

        self.worker = ConversionWorker(
            input_file=input_file,
            output_dir=output_dir,
            global_prompt=global_prompt,
            format_prompts_dict=format_prompts_dict,
            allocations=allocations,
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
