schema_trac_nghiem = {
    "type": "OBJECT",
    "properties": {
        "loai_de": {"type": "STRING", "enum": ["trac_nghiem_4_dap_an"]},
        "cau_hoi": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "_id": {"type": "STRING", "description": "Lấy chính xác _id từ câu gốc"},
                    "dvkt": {"type": "STRING", "description": "Lấy chính xác dvkt từ câu gốc"},
                    "muc_do": {"type": "STRING", "description": "Lấy mức độ từ câu gốc (vd: NB, TH, VD)"},
                    "stt": {"type": "INTEGER"},
                    "noi_dung": {"type": "STRING", "description": "Câu hỏi chi tiết"},
                    "hinh_anh": {
                        "type": "OBJECT",
                        "properties": {
                            "co_hinh": {"type": "BOOLEAN"},
                            "mo_ta": {"type": "STRING", "description": "Mô tả ảnh để AI vẽ (nếu cần)"}
                        }
                    },
                    "hinh_anh_giai_thich": {
                        "type": "OBJECT",
                        "properties": {
                            "co_hinh": {"type": "BOOLEAN"},
                            "mo_ta": {"type": "STRING", "description": "Mô tả ảnh phần giải thích để AI vẽ"}
                        }
                    },
                    "hinh_anh_goi_y": {
                        "type": "OBJECT",
                        "properties": {
                            "co_hinh": {"type": "BOOLEAN"},
                            "mo_ta": {"type": "STRING", "description": "Mô tả ảnh phần gợi ý để AI vẽ"}
                        }
                    },
                    "cac_lua_chon": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "ky_hieu": {"type": "STRING"},
                                "noi_dung": {"type": "STRING"}
                            },
                            "required": ["ky_hieu", "noi_dung"]
                        }
                    },
                    "dap_an_dung": {"type": "STRING", "description": "Ký hiệu đáp án đúng (A, B, C, D)"},
                    "giai_thich": {"type": "STRING"}
                },
                "required": ["_id", "dvkt", "stt", "noi_dung", "cac_lua_chon", "dap_an_dung", "giai_thich"]
            }
        }
    },
    "required": ["loai_de", "cau_hoi"]
}

schema_dung_sai = {
    "type": "OBJECT",
    "properties": {
        "loai_de": {"type": "STRING", "enum": ["dung_sai"]},
        "cau_hoi": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "_id": {"type": "STRING"},
                    "dvkt": {"type": "STRING"},
                    "muc_do": {"type": "STRING"},
                    "stt": {"type": "INTEGER"},
                    "doan_thong_tin": {"type": "STRING"},
                    "hinh_anh": {
                        "type": "OBJECT",
                        "properties": {
                            "co_hinh": {"type": "BOOLEAN"},
                            "mo_ta": {"type": "STRING"}
                        }
                    },
                    "hinh_anh_giai_thich": {
                        "type": "OBJECT",
                        "properties": {
                            "co_hinh": {"type": "BOOLEAN"},
                            "mo_ta": {"type": "STRING", "description": "Mô tả ảnh phần giải thích để AI vẽ"}
                        }
                    },
                    "hinh_anh_goi_y": {
                        "type": "OBJECT",
                        "properties": {
                            "co_hinh": {"type": "BOOLEAN"},
                            "mo_ta": {"type": "STRING", "description": "Mô tả ảnh phần gợi ý để AI vẽ"}
                        }
                    },
                    "cac_y": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "ky_hieu": {"type": "STRING", "description": "a, b, c, d"},
                                "noi_dung": {"type": "STRING"},
                                "dung": {"type": "BOOLEAN"}
                            },
                            "required": ["ky_hieu", "noi_dung", "dung"]
                        }
                    },
                    "dap_an_dung_sai": {"type": "STRING"},
                    "giai_thich": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "ky_hieu": {"type": "STRING"},
                                "ket_luan": {"type": "STRING", "description": "ĐÚNG hoặc SAI"},
                                "noi_dung": {"type": "STRING"}
                            },
                            "required": ["ky_hieu", "ket_luan", "noi_dung"]
                        }
                    }
                },
                "required": ["_id", "dvkt", "stt", "doan_thong_tin", "cac_y", "giai_thich"]
            }
        }
    },
    "required": ["loai_de", "cau_hoi"]
}

schema_tra_loi_ngan = {
    "type": "OBJECT",
    "properties": {
        "loai_de": {"type": "STRING", "enum": ["tra_loi_ngan"]},
        "cau_hoi": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "_id": {"type": "STRING"},
                    "dvkt": {"type": "STRING"},
                    "muc_do": {"type": "STRING"},
                    "stt": {"type": "INTEGER"},
                    "noi_dung": {"type": "STRING"},
                    "dap_an": {"type": "STRING", "description": "CHỈ CHỨA SỐ, cấm chữ/đơn vị"},
                    "hinh_anh": {
                        "type": "OBJECT",
                        "properties": {
                            "co_hinh": {"type": "BOOLEAN"},
                            "mo_ta": {"type": "STRING"}
                        }
                    },
                    "hinh_anh_giai_thich": {
                        "type": "OBJECT",
                        "properties": {
                            "co_hinh": {"type": "BOOLEAN"},
                            "mo_ta": {"type": "STRING", "description": "Mô tả ảnh phần giải thích để AI vẽ"}
                        }
                    },
                    "hinh_anh_goi_y": {
                        "type": "OBJECT",
                        "properties": {
                            "co_hinh": {"type": "BOOLEAN"},
                            "mo_ta": {"type": "STRING", "description": "Mô tả ảnh phần gợi ý để AI vẽ"}
                        }
                    },
                    "giai_thich": {"type": "STRING"}
                },
                "required": ["_id", "dvkt", "stt", "noi_dung", "dap_an", "giai_thich"]
            }
        }
    },
    "required": ["loai_de", "cau_hoi"]
}

schema_tu_luan = {
    "type": "OBJECT",
    "properties": {
        "loai_de": {"type": "STRING", "enum": ["tu_luan"]},
        "cau_hoi": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "_id": {"type": "STRING"},
                    "dvkt": {"type": "STRING"},
                    "muc_do": {"type": "STRING"},
                    "stt": {"type": "INTEGER"},
                    "noi_dung": {"type": "STRING"},
                    "hinh_anh": {
                        "type": "OBJECT",
                        "properties": {
                            "co_hinh": {"type": "BOOLEAN"},
                            "mo_ta": {"type": "STRING"}
                        }
                    },
                    "hinh_anh_giai_thich": {
                        "type": "OBJECT",
                        "properties": {
                            "co_hinh": {"type": "BOOLEAN"},
                            "mo_ta": {"type": "STRING", "description": "Mô tả ảnh phần giải thích để AI vẽ"}
                        }
                    },
                    "hinh_anh_goi_y": {
                        "type": "OBJECT",
                        "properties": {
                            "co_hinh": {"type": "BOOLEAN"},
                            "mo_ta": {"type": "STRING", "description": "Mô tả ảnh phần gợi ý để AI vẽ"}
                        }
                    },
                    "giai_thich": {"type": "STRING"}
                },
                "required": ["_id", "dvkt", "stt", "noi_dung", "giai_thich"]
            }
        }
    },
    "required": ["loai_de", "cau_hoi"]
}