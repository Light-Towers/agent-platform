import logging
from pathlib import Path

try:
    import markdown
except ImportError:
    markdown = None

try:
    from weasyprint import HTML as WeasyprintHTML
except ImportError:
    WeasyprintHTML = None


def convert_md_to_pdf_via_weasyprint(md_abs_path: Path, pdf_abs_path: Path) -> str:
    if WeasyprintHTML is None:
        return "缺少 weasyprint，请安装: pip install weasyprint"
    if markdown is None:
        return "缺少 markdown，请安装: pip install markdown"

    try:
        with open(md_abs_path, 'r', encoding='utf-8') as f:
            md_content = f.read()

        html_body = markdown.markdown(md_content, extensions=['tables', 'fenced_code'])
        html_content = f"""
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: "Noto Sans CJK SC", "WenQuanYi Micro Hei", "Microsoft YaHei", sans-serif; font-size: 14px; line-height: 1.6; }}
                table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
                th, td {{ border: 1px solid #ccc; padding: 8px; text-align: left; }}
                th {{ background-color: #f5f5f5; }}
                pre {{ background-color: #f5f5f5; padding: 10px; border-radius: 4px; overflow-x: auto; }}
                code {{ font-family: "Consolas", "Monaco", "Courier New", monospace; font-size: 13px; }}
                h1, h2, h3 {{ margin-top: 1.5em; }}
                blockquote {{ border-left: 3px solid #ccc; margin-left: 0; padding-left: 1em; color: #666; }}
            </style>
        </head>
        <body>
            {html_body}
        </body>
        </html>
        """

        WeasyprintHTML(string=html_content).write_pdf(str(pdf_abs_path))

        if pdf_abs_path.exists():
            return f"成功转换: {pdf_abs_path} (weasyprint)"
        else:
            return f"转换完成但未生成文件: {pdf_abs_path}"

    except Exception as e:
        logging.error("weasyprint 转换 PDF 失败: %s", e, exc_info=True)
        return f"转换失败: {str(e)}"


def convert_md_to_pdf_via_word(md_abs_path: Path, pdf_abs_path: Path) -> str:
    try:
        import win32com.client
        import pythoncom
    except ImportError:
        return convert_md_to_pdf_via_weasyprint(md_abs_path, pdf_abs_path)

    temp_html_path = md_abs_path.with_suffix('.temp.html')
    word_app = None

    try:
        with open(md_abs_path, 'r', encoding='utf-8') as f:
            md_content = f.read()

        html_body = markdown.markdown(md_content, extensions=['tables', 'fenced_code']) if markdown else md_content
        html_content = f"""
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: "Microsoft YaHei", "SimHei", sans-serif; }}
                table {{ border-collapse: collapse; width: 100%; }}
                th, td {{ border: 1px solid black; padding: 8px; }}
                pre {{ background-color: #f5f5f5; padding: 10px; border-radius: 4px; }}
                code {{ font-family: "Consolas", "Monaco", monospace; }}
            </style>
        </head>
        <body>
            {html_body}
        </body>
        </html>
        """

        with open(temp_html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        pythoncom.CoInitialize()
        word_app = win32com.client.Dispatch('Word.Application')
        word_app.Visible = False
        word_app.DisplayAlerts = False

        doc = word_app.Documents.Open(str(temp_html_path.resolve()))
        doc.SaveAs(str(pdf_abs_path.resolve()), FileFormat=17)
        doc.Close(SaveChanges=0)

        if pdf_abs_path.exists():
            return f"成功转换: {pdf_abs_path} (Word引擎)"
        else:
            return f"转换完成但未生成文件: {pdf_abs_path}"

    except ImportError:
        return convert_md_to_pdf_via_weasyprint(md_abs_path, pdf_abs_path)
    except Exception as e:
        logging.error("Word转换PDF失败: %s", e, exc_info=True)
        return f"转换失败: {str(e)}"

    finally:
        if word_app:
            try:
                word_app.Quit()
            except Exception:
                pass
        if temp_html_path.exists():
            try:
                temp_html_path.unlink()
            except Exception:
                pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass
