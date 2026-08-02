# -*- coding: utf-8 -*-
"""从中文 part1-5.py 生成英文版 part1-en.py~part5-en.py，并合并出 server-en.py。"""
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

BASE = r"D:\THU\Code\sharehub"

EN = {
    # ---- 通用 / 前台 ----
    "共享资源库": "ShareHub",
    "管理后台": "Admin Panel",
    "管理员登录": "Admin Login",
    "请输入管理员密码": "Enter admin password",
    "已选 ": "Selected ",
    " 项": " items",
    "请先选择文件": "Select files first",
    "返回上一级": "Up one level",
    "📁 根目录": "📁 Root",
    "🏠 根目录": "🏠 Root",
    "该文件夹为空": "This folder is empty",
    "这里空空如也": "Nothing here yet",
    "这里还没有内容": "Nothing here yet",
    "管理员上传文件后，就会展示在这里": "Files appear here after an admin uploads them",
    " 个文件 · ": " files · ",
    "文件夹": "folder",
    "文件": "file",
    " 资源": " files",
    "打开": "Open",
    "↓ 下载": "↓ Download",
    "下载": "Download",
    "</b><span>文件</span>": "</b><span>files</span>",
    "</b><span>已用空间</span>": "</b><span>used</span>",
    "</b><span>可用空间</span>": "</b><span>available</span>",
    "已用 ": "Used ",
    " · 预留 ": " · Reserved ",
    " · 缓存 ": " · Cache ",
    " · 可用 ": " · Free ",
    " · 总量 ": " · Total ",
    "第 ": "Page ",
    " 页 · 共 ": " of ",
    "搜索当前目录…": "Search current folder…",
    "搜索当前目录": "Search current folder",
    "全选当前目录": "Select all in folder",
    "↓ 打包下载 ZIP": "↓ Download ZIP",
    "池容量": "capacity",
    "资源总量": "total size",
    "管理入口": "Admin",
    "跳转": "Go",
    "🗑 删除": "🗑 Delete",
    "删除": "Delete",
    # ---- 后台任务/状态 ----
    "确认删除已选 ": "Delete selected ",
    " 项？此操作不可恢复。": " items? This cannot be undone.",
    "已删除 ": "Deleted ",
    "，失败 ": ", failed ",
    "删除失败": "Delete failed",
    "分片 ": "Chunk ",
    " 上传失败": " upload failed",
    "网络错误，可重试": "Network error, retryable",
    '<div class="tdone">✓ 全部上传完成 · ': '<div class="tdone">✓ All uploads complete · ',
    " 个文件</div>": " files</div>",
    " 个完成": " completed",
    " 个失败": " failed",
    " 个暂停": " paused",
    "上传完成：": "Uploaded: ",
    " · 分片 ": " · chunk ",
    "失败": "Failed",
    "重试": "Retry",
    "等待中": "Waiting",
    "已暂停 ": "Paused ",
    "继续": "Resume",
    "✓ 已完成": "✓ Done",
    "暂停": "Pause",
    "取消": "Cancel",
    " · 上传中 ": " · uploading ",
    " 个": " files",
    " · 队列 ": " · queue ",
    "任务 ": "Tasks ",
    "文件总数": "Total files",
    "已完成": "Done",
    "上传中": "Uploading",
    "等待": "Waiting",
    "所选内容共 ": "Selected total ",
    "，可用空间 ": ", available ",
    "，超出容量，未添加": ", exceeds capacity, not added",
    "拖拽文件/文件夹到上方，或点击按钮上传": "Drag files/folders above, or click the buttons to upload",
    "⚠ 已用 ": "⚠ Used ",
    " + 预留/缓存 ": " + reserved/cache ",
    " 超出容量 ": " exceeds capacity ",
    "，请删除文件": ", please delete files",
    "文件夹「": 'Folder "',
    "」（含全部内容）": '" (including everything)',
    "确认删除 ": "Delete ",
    "？此操作不可恢复。": "? This cannot be undone.",
    "新建文件夹名称": "New folder name",
    "新建文件夹": "New folder",
    "文件夹名称不能包含斜杠": "Folder name cannot contain slashes",
    "已创建文件夹 ": "Folder created: ",
    "创建失败": "Create failed",
    "没有失败的上传任务": "No failed uploads",
    "取消 ": "Cancel ",
    " 个失败的上传任务？其分片将保留为缓存。": " failed uploads? Their chunks are kept as cache.",
    "没有进行中的上传": "No uploads in progress",
    "取消全部 ": "Cancel all ",
    " 个上传任务？分片将保留，可稍后继续。": " uploads? Chunks are kept; you can resume later.",
    "加载中…": "Loading…",
    "加载失败": "Load failed",
    "共 ": "Total ",
    " 个会话": " sessions",
    '<div style="padding:30px;text-align:center;color:var(--muted)">暂无缓存</div>': '<div style="padding:30px;text-align:center;color:var(--muted)">No cache</div>',
    "<table class=\"cache-table\"><thead><tr><th>HASH</th><th>文件名</th><th>分片</th><th>大小</th><th>最后活动</th></tr></thead><tbody>": "<table class=\"cache-table\"><thead><tr><th>HASH</th><th>name</th><th>chunks</th><th>size</th><th>last active</th></tr></thead><tbody>",
    "清除所有未完成上传的临时分片？（已完成上传的文件不受影响）": "Clear all temp chunks of unfinished uploads? (Uploaded files are unaffected)",
    "已清理 ": "Cleared ",
    " 临时分片": " temp chunks",
    "清理失败": "Clear failed",
    "请输入当前管理员密码：": "Enter the current admin password:",
    "请输入新密码（至少 5 位）：": "Enter a new password (non-empty):",
    "新密码至少 5 位": "New password cannot be empty",
    "密码已修改": "Password changed",
    "修改失败": "Change failed",
    "设置池最大容量（GB，范围 0.5 ~ 200）：": "Set max pool capacity (GB, range 0.5 ~ 200):",
    "容量需在 0.5 ~ 200 GB 之间": "Capacity must be between 0.5 and 200 GB",
    "目标容量小于当前已用 ": "Target capacity is less than current usage ",
    "，请先删除部分文件": ", please delete some files",
    "池容量已设为 ": "Pool capacity set to ",
    "设置失败": "Set failed",
    # ---- 前台/后台 按钮与标签（三引号 HTML）----
    "☑ 多选": "☑ Multi-select",
    "📋 查看缓存": "📋 View cache",
    "🧹 清理缓存": "🧹 Clear cache",
    "⚖️ 修改容量": "⚖️ Change capacity",
    "🔑 修改密码": "🔑 Change password",
    "📄 日志": "📄 Logs",
    "🏠 回到前台": "🏠 Frontend",
    "🚪 退出": "🚪 Logout",
    "📄 选择文件": "📄 Select files",
    "📁 选择文件夹": "📁 Select folder",
    "☁️ 上传资源": "☁️ Upload",
    "⏸ 全部暂停": "⏸ Pause all",
    "▶ 全部继续": "▶ Resume all",
    "↻ 全部重试": "↻ Retry all",
    "✖ 取消失败": "✖ Drop failed",
    "✕ 全部取消": "✕ Cancel all",
    "← 上一页": "← Prev",
    "下一页 →": "Next →",
    "跳至": "Go to ",
    ">页</span>": " page</span>",
    ">页<button": " page<button",
    "返回资源库": "Back to library",
    "登 录": "Log in",
    "拖拽文件或文件夹到此处，或点击选择文件": "Drag files or folders here, or click to select",
    "单个文件最大 10GB · 3 并发分片 · 断点可续传": "",
    "3 并发分片 · 断点可续传": "3-way chunked upload · resumable",
    "服务器日志（最近 300 行）": "Server log (last 300 lines)",
    "上传缓存（临时分片）": "Upload cache (temp chunks)",
    "✕ 关闭": "✕ Close",
    # ---- 服务器错误/消息 ----
    "没有可打包的项目": "Nothing to archive",
    "操作成功": "Operation succeeded",
    "未找到": "Not Found",
    "文件不存在": "File not found",
    "请先登录": "Please log in",
    "会话不存在": "Session not found",
    "（暂无日志文件）": "(no log file yet)",
    "页面不存在": "Page not found",
    "密码错误": "Wrong password",
    "上传会话不存在，请重新选择文件": "Upload session missing, please reselect the file",
    "分片越界": "Chunk out of range",
    "分片超过 5MB 限制": "Chunk exceeds the 5MB limit",
    "分片长度不匹配，请重传此片": "Chunk length mismatch, please re-upload this chunk",
    "校验参数不合法": "Invalid checksum parameter",
    "分片校验失败（内容不符），请重传此片": "Chunk checksum failed (content mismatch), please re-upload",
    "参数不合法": "Invalid parameter",
    "非法路径": "Illegal path",
    "已存在同名文件夹": "A folder with the same name exists",
    "无法写入：路径中存在同名文件 ": "Cannot write: a file exists at path ",
    "池容量不足，剩余 %s，需要 %s": "Not enough capacity: %s left, %s needed",
    "上传会话不存在": "Upload session not found",
    "还有 %d 个分片未上传": "%d chunks not yet uploaded",
    "分片数据异常，请重新上传": "Chunk data error, please re-upload",
    "合并后大小校验失败": "Merged file size check failed",
    "写入失败，磁盘可能已满": "Write failed, disk may be full",
    "旧密码错误": "Wrong old password",
    "新密码不能为空": "New password cannot be empty",
    "当前已用 %s，超过目标容量 %s，请先删除部分文件或设置更大容量": "Currently using %s, exceeds target %s; delete files or set a larger capacity",
    "同名文件夹已存在": "A folder with the same name exists",
    "目标不存在": "Target not found",
    "未知操作": "Unknown operation",
    "没有选择项目": "Nothing selected",
}

# 长串优先替换，避免短串先替换破坏长串
pairs = sorted(EN.items(), key=lambda kv: -len(kv[0]))


def translate_text(txt):
    for zh, en in pairs:
        if zh:
            txt = txt.replace(zh, en)
    return txt


def main():
    for i in range(1, 6):
        src = os.path.join(BASE, f"part{i}.py")
        dst = os.path.join(BASE, f"part{i}-en.py")
        txt = open(src, encoding="utf-8-sig").read()
        out = translate_text(txt)
        open(dst, "w", encoding="utf-8").write(out)
        remain = len(re.findall(r"[\u4e00-\u9fff]", out))
        print(f"part{i}-en.py 生成，剩余中文字符: {remain}")

    parts = [os.path.join(BASE, f"part{i}-en.py") for i in range(1, 6)]
    merged = "".join(open(p, encoding="utf-8-sig").read() for p in parts)
    open(os.path.join(BASE, "server-en.py"), "w", encoding="utf-8").write(merged)
    remain_all = len(re.findall(r"[\u4e00-\u9fff]", merged))
    print(f"server-en.py 生成，总剩余中文字符: {remain_all}")


if __name__ == "__main__":
    main()
