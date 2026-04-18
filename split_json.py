import os
import re

def split_json(input_file, output_folder="output"):
    """
    Reads a large MongoDB-exported JSON file line by line.
    To avoid memory issues, it streams the file.
    To avoid counting braces inside string literals (which caused missing questions),
    it removes string literals using Regex before counting structural braces.
    """
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    # Regex to extract dvkt safely
    dvkt_regex = re.compile(r'"dvkt"\s*:\s*"([^"]+)"')
    
    # Regex to remove string literals: match quotes, ignore escaped quotes
    string_literal_regex = re.compile(r'"(?:\\.|[^"\\])*"')

    print(f"Start processing file: {input_file}")
    
    current_dvkt = None
    current_subject = None
    
    brace_count = 0
    in_question = False
    question_buffer = []
    
    count = 0

    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            for line in f:
                # 1. Strip strings from the line
                line_no_strings = string_literal_regex.sub('', line)
                
                # If we are not currently in a question, ignore root [ and ]
                if not in_question:
                    line_no_strings = line_no_strings.replace('[', '').replace(']', '')
                
                # Track the change in braces on this line
                braces_delta = line_no_strings.count('{') - line_no_strings.count('}')
                
                # If we are starting a new question on this line
                if not in_question and (brace_count + braces_delta) > 0:
                    in_question = True
                    question_buffer = []  # Start fresh
                
                if in_question:
                    question_buffer.append(line)
                    brace_count += braces_delta
                    
                    if not current_dvkt:
                        match = dvkt_regex.search(line)
                        if match:
                            current_dvkt = match.group(1)
                            current_subject = current_dvkt.split('_')[0]
                            
                    # If this line closed the question
                    if brace_count == 0:
                        in_question = False
                        
                        if current_dvkt and current_subject:
                            # We have a full, valid question object!
                            count += 1
                            if count % 5000 == 0:
                                print(f"Processed {count} questions...", flush=True)
                                
                            subject_folder = os.path.join(output_folder, current_subject)
                            if not os.path.exists(subject_folder):
                                os.makedirs(subject_folder)
                                
                            out_filepath = os.path.join(subject_folder, f"{current_dvkt}.json")
                            is_new_file = not os.path.exists(out_filepath)
                            
                            # Clean up buffer (remove optional array brackets from the first question)
                            buffer_str = "".join(question_buffer).strip()
                            if buffer_str.startswith('[{'):
                                buffer_str = buffer_str[1:].strip()
                                
                            # Clean up trailing comma
                            if buffer_str.endswith(','):
                                buffer_str = buffer_str[:-1]
                                
                            with open(out_filepath, 'a', encoding='utf-8') as out_f:
                                if is_new_file:
                                    out_f.write("[\n" + buffer_str)
                                else:
                                    out_f.write(",\n" + buffer_str)
                                    
                        # Reset for the next object
                        question_buffer = []
                        current_dvkt = None
                        current_subject = None
                        
    except Exception as e:
        print(f"Error reading file: {e}")
        import traceback
        traceback.print_exc()
        return

    print("Closing JSON arrays for output files...")
    for root, dirs, files in os.walk(output_folder):
        for file in files:
            if file.endswith('.json'):
                filepath = os.path.join(root, file)
                with open(filepath, 'a', encoding='utf-8') as f:
                    f.write("\n]")
                    
    print(f"Finished! Total: {count} questions. Saved in: {os.path.abspath(output_folder)}")

if __name__ == "__main__":
    import sys
    # Support command line args for easier execution
    input_filename = r"d:\data_input_ai_21012025.json"
    output_dirname = r"d:\CheckTool\SinhCauHoiTuongTu\split_output"
    
    if len(sys.argv) > 1:
        input_filename = sys.argv[1]
    
    print("--------------------------------------------------")
    print("ROBUST JSON SPLITTER")
    print("Using safe string-stripping brace counter.")
    split_json(input_filename, output_dirname)
