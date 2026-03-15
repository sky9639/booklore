package org.booklore.print;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.io.File;
import java.io.FileInputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.booklore.model.entity.BookEntity;
import org.booklore.print.dto.PrintRequest;
import org.booklore.repository.BookRepository;
import org.springframework.core.io.InputStreamResource;
import org.springframework.core.io.Resource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.MediaTypeFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@RestController
@RequestMapping("/api/v1/print")
@RequiredArgsConstructor
public class PrintController {

    private final PrintEngineClient client;
    private final BookRepository bookRepository;

    /**
     * ===============================
     * 初始化 Print Workspace
     * ===============================
     * POST /api/v1/print/{bookId}/workspace/init
     */
    @PostMapping("/{bookId}/workspace/init")
    public ResponseEntity<?> initWorkspace(@PathVariable Long bookId) {
        BookEntity book = bookRepository
            .findById(bookId)
            .orElseThrow(() -> new RuntimeException("Book not found"));

        Path fullPath = book.getFullFilePath();
        if (fullPath == null) {
            return ResponseEntity.badRequest().body(
                Map.of("error", "Book file path could not be resolved")
            );
        }

        Map<String, Object> payload = new HashMap<>();
        payload.put("book_path", fullPath.toString());
        payload.put("book_id", book.getId());
        payload.putAll(extractBookMeta(book));

        Map result = client.initWorkspace(payload);
        return ResponseEntity.ok(result);
    }

    /**
     * ===============================
     * 上传封面 / 书脊 / 封底素材
     * ===============================
     * POST /api/v1/print/{bookId}/workspace/upload/{category}
     */
    @PostMapping("/{bookId}/workspace/upload/{category}")
    public ResponseEntity<?> uploadMaterial(
        @PathVariable Long bookId,
        @PathVariable String category,
        @RequestParam(
            "file"
        ) org.springframework.web.multipart.MultipartFile file
    ) {
        try {
            BookEntity book = bookRepository
                .findById(bookId)
                .orElseThrow(() -> new RuntimeException("Book not found"));

            Path fullPath = book.getFullFilePath();
            if (fullPath == null) {
                return ResponseEntity.badRequest().body(
                    Map.of("error", "Book file path could not be resolved")
                );
            }

            if (
                !category.equals("cover") &&
                !category.equals("spine") &&
                !category.equals("back")
            ) {
                return ResponseEntity.badRequest().body(
                    Map.of("error", "invalid category")
                );
            }

            Path printRoot = fullPath.getParent().resolve(".print");
            Path targetDir = printRoot.resolve(category);
            targetDir.toFile().mkdirs();

            // 获取原始文件名和扩展名
            String original = file.getOriginalFilename();
            if (original == null) original = "image.jpg";

            // 提取扩展名
            String extension = "";
            int dotIndex = original.lastIndexOf('.');
            if (dotIndex > 0 && dotIndex < original.length() - 1) {
                extension = original.substring(dotIndex); // 包含点号，如 ".jpg"
            } else {
                extension = ".jpg"; // 默认扩展名
            }

            // 使用时间戳 + 扩展名作为文件名，避免特殊字符问题
            String filename = System.currentTimeMillis() + extension;
            Path target = targetDir.resolve(filename);
            file.transferTo(target.toFile());

            Map<String, Object> workspace = updateWorkspaceJson(
                printRoot,
                category,
                filename
            );
            return ResponseEntity.ok(workspace);
        } catch (Exception e) {
            return ResponseEntity.internalServerError().body(
                Map.of("error", e.getMessage())
            );
        }
    }

    /**
     * ===============================
     * 生成拼版预览
     * ===============================
     * POST /api/v1/print/{bookId}/preview
     */
    @PostMapping("/{bookId}/preview")
    public ResponseEntity<?> preview(
        @PathVariable Long bookId,
        @RequestBody PrintRequest request
    ) {
        BookEntity book = bookRepository
            .findById(bookId)
            .orElseThrow(() -> new RuntimeException("Book not found"));

        Path fullPath = book.getFullFilePath();
        if (fullPath == null) {
            return ResponseEntity.badRequest().body(
                Map.of("error", "Book file path could not be resolved")
            );
        }

        Map<String, Object> payload = new HashMap<>();
        payload.put("book_path", fullPath.toString());
        payload.put("paper_thickness", request.getPaperThickness());
        payload.put("page_count", request.getPageCount());
        payload.put("spine_mode", request.getSpineMode());
        payload.put("back_mode", request.getBackMode());
        payload.put("book_id", book.getId());
        payload.putAll(extractBookMeta(book));

        Map<String, Object> result = client.preview(payload);
        return ResponseEntity.ok(result);
    }

    /**
     * ===============================
     * 生成最终 PDF
     * ===============================
     * POST /api/v1/print/{bookId}/pdf
     */
    @PostMapping("/{bookId}/pdf")
    public ResponseEntity<?> generatePdf(
        @PathVariable Long bookId,
        @RequestBody PrintRequest request
    ) {
        BookEntity book = bookRepository
            .findById(bookId)
            .orElseThrow(() -> new RuntimeException("Book not found"));

        Path fullPath = book.getFullFilePath();
        if (fullPath == null) {
            return ResponseEntity.badRequest().body(
                Map.of("error", "Book file path could not be resolved")
            );
        }

        Map<String, Object> payload = new HashMap<>();
        payload.put("book_path", fullPath.toString());
        payload.put("paper_thickness", request.getPaperThickness());
        payload.put("page_count", request.getPageCount());
        payload.put("spine_mode", request.getSpineMode());
        payload.put("back_mode", request.getBackMode());
        payload.put("book_id", book.getId());
        payload.put(
            "trim_size",
            request.getTrimSize() != null ? request.getTrimSize() : "A5"
        );
        payload.putAll(extractBookMeta(book));

        Map result = client.generate(payload);
        return ResponseEntity.ok(result);
    }

    /**
     * ===============================
     * 下载生成后的 PDF（旧接口保留兼容）
     * ===============================
     * GET /api/v1/print/pdf?path=...
     */
    @GetMapping("/pdf")
    public ResponseEntity<Resource> downloadPdf(@RequestParam String path) {
        try {
            File file = new File(path);
            if (!file.exists() || !file.getName().endsWith(".pdf")) {
                return ResponseEntity.notFound().build();
            }
            InputStreamResource resource = new InputStreamResource(
                new FileInputStream(file)
            );
            return ResponseEntity.ok()
                .header(
                    HttpHeaders.CONTENT_DISPOSITION,
                    "attachment; filename=" + file.getName()
                )
                .contentLength(file.length())
                .contentType(MediaType.APPLICATION_PDF)
                .body(resource);
        } catch (Exception e) {
            return ResponseEntity.internalServerError().build();
        }
    }

    /**
     * ===============================
     * PDF inline 查看（供 PDF.js）
     * ===============================
     * GET /api/v1/print/{bookId}/pdf/view
     */
    @GetMapping("/{bookId}/pdf/view")
    public ResponseEntity<Resource> viewPdf(@PathVariable Long bookId) {
        try {
            BookEntity book = bookRepository
                .findById(bookId)
                .orElseThrow(() -> new RuntimeException("Book not found"));

            Path fullPath = book.getFullFilePath();
            if (fullPath == null) return ResponseEntity.notFound().build();

            // 从 workspace.json 读取实际的 PDF 文件名
            Path printDir = fullPath.getParent().resolve(".print");
            Path workspaceFile = printDir.resolve("workspace.json");

            File file = null;
            String filename = "layout_print.pdf";

            if (workspaceFile.toFile().exists()) {
                try {
                    String json = Files.readString(workspaceFile);
                    com.fasterxml.jackson.databind.ObjectMapper mapper = new com.fasterxml.jackson.databind.ObjectMapper();
                    com.fasterxml.jackson.databind.JsonNode ws = mapper.readTree(json);
                    String pdfPath = ws.has("pdf_path") ? ws.get("pdf_path").asText() : null;

                    if (pdfPath != null && !pdfPath.isEmpty()) {
                        file = new File(pdfPath);
                        filename = file.getName();
                    }
                } catch (Exception e) {
                    // 读取失败，使用默认文件名
                }
            }

            // 如果没有从 workspace 读取到，使用默认路径
            if (file == null || !file.exists()) {
                file = printDir.resolve("layout_print.pdf").toFile();
                filename = "layout_print.pdf";
            }

            if (!file.exists()) return ResponseEntity.notFound().build();

            InputStreamResource resource = new InputStreamResource(
                new FileInputStream(file)
            );
            return ResponseEntity.ok()
                .header(
                    HttpHeaders.CONTENT_DISPOSITION,
                    "inline; filename=" + filename
                )
                .header(HttpHeaders.ACCESS_CONTROL_ALLOW_ORIGIN, "*")
                .contentLength(file.length())
                .contentType(MediaType.APPLICATION_PDF)
                .body(resource);
        } catch (Exception e) {
            return ResponseEntity.internalServerError().build();
        }
    }

    /**
     * ===============================
     * PDF 下载
     * ===============================
     * GET /api/v1/print/{bookId}/pdf/download
     */
    @GetMapping("/{bookId}/pdf/download")
    public ResponseEntity<Resource> downloadPdfByBookId(
        @PathVariable Long bookId
    ) {
        try {
            BookEntity book = bookRepository
                .findById(bookId)
                .orElseThrow(() -> new RuntimeException("Book not found"));

            Path fullPath = book.getFullFilePath();
            if (fullPath == null) return ResponseEntity.notFound().build();

            // 从 workspace.json 读取实际的 PDF 文件名
            Path printDir = fullPath.getParent().resolve(".print");
            Path workspaceFile = printDir.resolve("workspace.json");

            File file = null;
            String filename = "layout_print.pdf";

            if (workspaceFile.toFile().exists()) {
                try {
                    String json = Files.readString(workspaceFile);
                    com.fasterxml.jackson.databind.ObjectMapper mapper = new com.fasterxml.jackson.databind.ObjectMapper();
                    com.fasterxml.jackson.databind.JsonNode ws = mapper.readTree(json);
                    String pdfPath = ws.has("pdf_path") ? ws.get("pdf_path").asText() : null;

                    if (pdfPath != null && !pdfPath.isEmpty()) {
                        file = new File(pdfPath);
                        filename = file.getName();
                    }
                } catch (Exception e) {
                    // 读取失败，使用默认文件名
                }
            }

            // 如果没有从 workspace 读取到，使用默认路径
            if (file == null || !file.exists()) {
                file = printDir.resolve("layout_print.pdf").toFile();
                filename = "layout_print.pdf";
            }

            if (!file.exists()) return ResponseEntity.notFound().build();

            InputStreamResource resource = new InputStreamResource(
                new FileInputStream(file)
            );
            return ResponseEntity.ok()
                .header(
                    HttpHeaders.CONTENT_DISPOSITION,
                    "attachment; filename=\"" + filename + "\""
                )
                .contentLength(file.length())
                .contentType(MediaType.APPLICATION_PDF)
                .body(resource);
        } catch (Exception e) {
            return ResponseEntity.internalServerError().build();
        }
    }

    /**
     * ===============================
     * 访问素材图片
     * ===============================
     * GET /api/v1/print/{bookId}/asset/{category}/{filename}
     */
    @GetMapping("/{bookId}/asset/{category}/{filename}")
    public ResponseEntity<Resource> getAsset(
        @PathVariable Long bookId,
        @PathVariable String category,
        @PathVariable String filename
    ) {
        try {
            BookEntity book = bookRepository
                .findById(bookId)
                .orElseThrow(() -> new RuntimeException("Book not found"));

            Path fullPath = book.getFullFilePath();
            if (fullPath == null) return ResponseEntity.notFound().build();

            File file = fullPath
                .getParent()
                .resolve(".print")
                .resolve(category)
                .resolve(filename)
                .toFile();
            if (
                !file.exists() || !file.isFile()
            ) return ResponseEntity.notFound().build();

            InputStreamResource resource = new InputStreamResource(
                new FileInputStream(file)
            );
            return ResponseEntity.ok()
                .contentLength(file.length())
                .contentType(
                    MediaTypeFactory.getMediaType(file.getName()).orElse(
                        MediaType.APPLICATION_OCTET_STREAM
                    )
                )
                .body(resource);
        } catch (Exception e) {
            return ResponseEntity.internalServerError().build();
        }
    }

    /**
     * ===============================
     * 删除素材
     * ===============================
     * DELETE /api/v1/print/{bookId}/material?category=&filename=
     */
    @DeleteMapping("/{bookId}/material")
    public ResponseEntity<?> deleteMaterial(
        @PathVariable Long bookId,
        @RequestParam String category,
        @RequestParam String filename
    ) {
        try {
            BookEntity book = bookRepository
                .findById(bookId)
                .orElseThrow(() -> new RuntimeException("Book not found"));

            Path fullPath = book.getFullFilePath();
            if (fullPath == null) {
                return ResponseEntity.badRequest().body(
                    Map.of("error", "Book file path could not be resolved")
                );
            }

            Path printRoot = fullPath.getParent().resolve(".print");
            Path workspaceFile = printRoot.resolve("workspace.json");

            ObjectMapper mapper = new ObjectMapper();
            if (!Files.exists(workspaceFile)) {
                return ResponseEntity.badRequest().body(
                    Map.of("error", "workspace.json not found")
                );
            }

            ObjectNode workspace = (ObjectNode) mapper.readTree(
                workspaceFile.toFile()
            );

            if (workspace.has(category)) {
                ObjectNode section = (ObjectNode) workspace.get(category);

                // 从 history 删除
                if (section.has("history")) {
                    ArrayNode history = (ArrayNode) section.get("history");
                    for (int i = 0; i < history.size(); i++) {
                        if (filename.equals(history.get(i).asText())) {
                            history.remove(i);
                            break;
                        }
                    }
                }

                // 若删除的是 selected，自动切换到 history 第一个
                if (
                    section.has("selected") && !section.get("selected").isNull()
                ) {
                    if (filename.equals(section.get("selected").asText())) {
                        ArrayNode history = section.has("history")
                            ? (ArrayNode) section.get("history")
                            : null;
                        if (history != null && history.size() > 0) {
                            section.put("selected", history.get(0).asText());
                        } else {
                            section.putNull("selected");
                        }
                    }
                }
            }

            // 删除文件
            Files.deleteIfExists(printRoot.resolve(category).resolve(filename));

            mapper
                .writerWithDefaultPrettyPrinter()
                .writeValue(workspaceFile.toFile(), workspace);
            return ResponseEntity.ok(mapper.convertValue(workspace, Map.class));
        } catch (Exception e) {
            return ResponseEntity.internalServerError().body(
                Map.of("error", e.getMessage())
            );
        }
    }

    /**
     * ===============================
     * 切换选中素材
     * ===============================
     * POST /api/v1/print/{bookId}/select?category=&filename=
     */
    @PostMapping("/{bookId}/select")
    public ResponseEntity<?> selectMaterial(
        @PathVariable Long bookId,
        @RequestParam String category,
        @RequestParam String filename
    ) {
        try {
            BookEntity book = bookRepository
                .findById(bookId)
                .orElseThrow(() -> new RuntimeException("Book not found"));

            Path fullPath = book.getFullFilePath();
            Path printRoot = fullPath.getParent().resolve(".print");
            Path workspaceFile = printRoot.resolve("workspace.json");

            ObjectMapper mapper = new ObjectMapper();
            ObjectNode workspace = (ObjectNode) mapper.readTree(
                workspaceFile.toFile()
            );
            ObjectNode section = (ObjectNode) workspace.get(category);

            if (section == null) {
                return ResponseEntity.badRequest().body(
                    Map.of("error", "invalid category")
                );
            }

            section.put("selected", filename);
            mapper
                .writerWithDefaultPrettyPrinter()
                .writeValue(workspaceFile.toFile(), workspace);
            return ResponseEntity.ok(mapper.convertValue(workspace, Map.class));
        } catch (Exception e) {
            return ResponseEntity.internalServerError().body(
                Map.of("error", e.getMessage())
            );
        }
    }

    /**
     * ============================================================
     * AI 生成书脊 / 封底
     *
     * POST /api/v1/print/{bookId}/workspace/ai-generate?target=spine|back
     *
     * 流程：
     *   1. 构造 payload 发给 print-engine /ai-generate
     *   2. print-engine 返回 PNG bytes
     *   3. Java 侧命名文件：ai_{target}_{timestamp}.png
     *   4. 保存到 .print/{target}/
     *   5. 更新 workspace.json（复用 uploadMaterial 相同逻辑）
     *   6. 返回完整 workspace JSON（前端用 asset 接口拼图片 URL）
     * ============================================================
     */
    @PostMapping("/{bookId}/workspace/ai-generate")
    public ResponseEntity<?> aiGenerateMaterial(
        @PathVariable Long bookId,
        @RequestParam String target,
        @RequestBody PrintRequest request
    ) {
        try {
            if (
                !target.equals("all") &&
                !target.equals("spine") &&
                !target.equals("back")
            ) {
                return ResponseEntity.badRequest().body(
                    Map.of("error", "target 必须是 all / spine / back")
                );
            }

            BookEntity book = bookRepository
                .findById(bookId)
                .orElseThrow(() -> new RuntimeException("Book not found"));

            Path fullPath = book.getFullFilePath();
            if (fullPath == null) {
                return ResponseEntity.badRequest().body(
                    Map.of("error", "Book file path could not be resolved")
                );
            }

            // ── 1. 构造发给 print-engine 的 payload ──────────────────────────
            Map<String, Object> payload = new HashMap<>();
            payload.put("book_path", fullPath.toString());
            payload.put("target", target);
            payload.put(
                "trim_size",
                request.getTrimSize() != null ? request.getTrimSize() : "A5"
            );

            double paperThickness =
                request.getPaperThickness() != null
                    ? request.getPaperThickness()
                    : 0.06;
            int pageCount =
                request.getPageCount() != null ? request.getPageCount() : 0;
            payload.put("paper_thickness", paperThickness);
            payload.put("book_page_count", pageCount);

            if (book.getMetadata() != null) {
                var meta = book.getMetadata();

                payload.put(
                    "book_title",
                    meta.getTitle() != null ? meta.getTitle() : ""
                );

                List<String> authors = new ArrayList<>();
                if (meta.getAuthors() != null) {
                    meta.getAuthors().forEach(a -> authors.add(a.getName()));
                }
                payload.put("authors", authors); // Fix: Python expects list[str], not joined String

                String desc = meta.getDescription();
                if (desc != null && desc.length() > 800) desc = desc.substring(
                    0,
                    800
                );
                payload.put("description", desc != null ? desc : ""); // Fix: Python expects "description" not "book_description"
            }

            // ── 2. 调用 print-engine，拿回 PNG bytes ─────────────────────────
            byte[] imageBytes = client.aiGenerate(payload);

            // ── 3. 命名：ai_{target}_{yyyyMMdd_HHmmss}.png ───────────────────
            String timestamp = LocalDateTime.now().format(
                DateTimeFormatter.ofPattern("yyyyMMdd_HHmmss")
            );
            String filename = "ai_" + target + "_" + timestamp + ".png";

            // ── 4. 保存到 .print/{target}/ ───────────────────────────────────
            Path printRoot = fullPath.getParent().resolve(".print");
            Path targetDir = printRoot.resolve(target);
            targetDir.toFile().mkdirs();
            Files.write(targetDir.resolve(filename), imageBytes);

            // ── 5. 更新 workspace.json（与手工上传完全相同的逻辑）────────────
            Map<String, Object> workspace = updateWorkspaceJson(
                printRoot,
                target,
                filename
            );

            // ── 6. 返回 workspace JSON，前端用 asset 接口拼 URL ──────────────
            return ResponseEntity.ok(workspace);
        } catch (Exception e) {
            return ResponseEntity.internalServerError().body(
                Map.of("error", e.getMessage())
            );
        }
    }

    // ============================================================
    // 私有工具方法
    // ============================================================

    /**
     * ============================================================
     * AI 生成进度 SSE 接口
     *
     * 流程：
     *   1. POST /workspace/ai-generate/start → Python 返回 task_id
     *   2. GET  /workspace/ai-generate/progress/{bookId} → 转发 Python SSE 流给前端
     *
     * 前端收到 {"pct":100,"status":"done","ws":{...}} 后刷新缩略图
     * ============================================================
     */

    /**
     * POST /api/v1/print/{bookId}/workspace/ai-generate/start
     * 启动 AI 生成任务，立即返回 task_id
     */
    @PostMapping("/{bookId}/workspace/ai-generate/start")
    public ResponseEntity<?> aiGenerateStart(
        @PathVariable Long bookId,
        @RequestBody Map<String, Object> body
    ) {
        try {
            // target 由前端放在 request body 里（"all" | "spine" | "back"）
            String target = body.getOrDefault("target", "all").toString();
            if (
                !target.equals("all") &&
                !target.equals("spine") &&
                !target.equals("back")
            ) {
                return ResponseEntity.badRequest().body(
                    Map.of("error", "target 必须是 all / spine / back")
                );
            }
            // 从 body 重建 PrintRequest
            PrintRequest request = new PrintRequest();
            if (body.containsKey("trimSize")) request.setTrimSize(
                body.get("trimSize").toString()
            );
            if (body.containsKey("pageCount")) request.setPageCount(
                Integer.valueOf(body.get("pageCount").toString())
            );
            if (body.containsKey("paperThickness")) request.setPaperThickness(
                Double.valueOf(body.get("paperThickness").toString())
            );

            BookEntity book = bookRepository
                .findById(bookId)
                .orElseThrow(() -> new RuntimeException("Book not found"));

            Path fullPath = book.getFullFilePath();
            if (fullPath == null) {
                return ResponseEntity.badRequest().body(
                    Map.of("error", "Book file path could not be resolved")
                );
            }

            Map<String, Object> payload = new HashMap<>();
            payload.put("book_path", fullPath.toString());
            payload.put("target", target);
            payload.put(
                "trim_size",
                request.getTrimSize() != null ? request.getTrimSize() : "A5"
            );

            double paperThickness =
                request.getPaperThickness() != null
                    ? request.getPaperThickness()
                    : 0.06;
            int pageCount =
                request.getPageCount() != null ? request.getPageCount() : 0;
            payload.put("paper_thickness", paperThickness);
            payload.put("book_page_count", pageCount);

            // ── 必填项校验：封面 + 书名 ──────────────────────────────────────
            var meta = book.getMetadata();

            // 1. 书名（必填）
            String bookTitle = (meta != null && meta.getTitle() != null)
                ? meta.getTitle().trim()
                : "";
            if (bookTitle.isEmpty()) {
                return ResponseEntity.badRequest().body(
                    Map.of(
                        "error",
                        "缺少书名，请在图书详情页补充元数据后再生成"
                    )
                );
            }

            // 2. 作者（可选，默认 "Unknown Author"）
            List<String> authors = new ArrayList<>();
            if (meta != null && meta.getAuthors() != null) {
                meta
                    .getAuthors()
                    .forEach(a -> {
                        if (
                            a.getName() != null && !a.getName().isBlank()
                        ) authors.add(a.getName());
                    });
            }
            if (authors.isEmpty()) {
                authors.add("Unknown Author");
            }

            // 3. 简介（可选，默认通用描述）
            String desc = (meta != null) ? meta.getDescription() : null;
            if (desc == null || desc.isBlank()) {
                desc = "A captivating story that will keep you turning pages.";
            }
            if (desc.length() > 800) desc = desc.substring(0, 800);

            // 4. 分类（可选，默认 "children's book, cartoon style"）
            List<String> categories = new ArrayList<>();
            if (meta != null && meta.getCategories() != null && !meta.getCategories().isEmpty()) {
                meta.getCategories().forEach(cat -> {
                    if (cat.getName() != null && !cat.getName().isBlank()) {
                        categories.add(cat.getName());
                    }
                });
            }
            if (categories.isEmpty()) {
                categories.add("children's book");
                categories.add("cartoon style");
            }

            // ── 组装 payload ──────────────────────────────────────────────────
            payload.put("book_title", bookTitle);
            payload.put("authors", authors);
            payload.put("description", desc);
            payload.put("categories", categories);
            payload.put(
                "spine_width_mm",
                request.getPaperThickness() != null &&
                    request.getPageCount() != null
                    ? Math.round(
                          request.getPageCount() *
                              request.getPaperThickness() *
                              100.0
                      ) /
                      100.0
                    : 4.74
            );

            // 调用 Python /workspace/ai-generate/start，拿 task_id
            Map result = client.aiGenerateStart(payload);
            return ResponseEntity.ok(result);
        } catch (Exception e) {
            return ResponseEntity.internalServerError().body(
                Map.of("error", e.getMessage())
            );
        }
    }

    /**
     * GET /api/v1/print/{bookId}/workspace/ai-generate/progress/{taskId}
     * 转发 Python SSE 进度流给前端
     */
    @GetMapping(
        value = "/{bookId}/workspace/ai-generate/progress/{taskId}",
        produces = "text/event-stream"
    )
    public SseEmitter aiGenerateProgress(
        @PathVariable Long bookId,
        @PathVariable String taskId
    ) {
        SseEmitter emitter = new SseEmitter(700_000L); // 700 秒超时

        Thread.ofVirtual().start(() -> {
            try (
                java.io.InputStream is = openSseStream(
                    "http://print-engine:5000/workspace/ai-generate/progress/" +
                        taskId
                );
                java.io.BufferedReader reader = new java.io.BufferedReader(
                    new java.io.InputStreamReader(
                        is,
                        java.nio.charset.StandardCharsets.UTF_8
                    )
                )
            ) {
                String line;
                while ((line = reader.readLine()) != null) {
                    if (line.startsWith("data: ")) {
                        String data = line.substring(6);
                        emitter.send(
                            SseEmitter.event().data(
                                data,
                                MediaType.APPLICATION_JSON
                            )
                        );
                        // done 或 error 时结束
                        if (
                            data.contains("\"done\"") ||
                            data.contains("\"error\"")
                        ) {
                            emitter.complete();
                            return;
                        }
                    }
                }
                emitter.complete();
            } catch (Exception e) {
                emitter.completeWithError(e);
            }
        });

        return emitter;
    }

    // ============================================================

    /**
     * 更新 workspace.json 中指定 category 的 selected + history。
     * uploadMaterial 和 aiGenerateMaterial 共用此方法，确保逻辑完全一致。
     */

    private java.io.InputStream openSseStream(String url)
        throws java.io.IOException {
        java.net.HttpURLConnection conn =
            (java.net.HttpURLConnection) new java.net.URL(url).openConnection();
        conn.setConnectTimeout(10_000);
        conn.setReadTimeout(720_000); // 12分钟，覆盖两次生成
        conn.setRequestProperty("Accept", "text/event-stream");
        conn.setRequestProperty("Cache-Control", "no-cache");
        return conn.getInputStream();
    }

    private Map<String, Object> updateWorkspaceJson(
        Path printRoot,
        String category,
        String filename
    ) throws Exception {
        Path workspaceFile = printRoot.resolve("workspace.json");
        ObjectMapper mapper = new ObjectMapper();

        ObjectNode workspace;
        if (Files.exists(workspaceFile)) {
            workspace = (ObjectNode) mapper.readTree(workspaceFile.toFile());
        } else {
            workspace = mapper.createObjectNode();
        }

        ObjectNode section = workspace.has(category)
            ? (ObjectNode) workspace.get(category)
            : mapper.createObjectNode();

        // selected
        section.put("selected", filename);

        // history：去重 + 插入最前 + 限制5个
        ArrayNode history = section.has("history")
            ? (ArrayNode) section.get("history")
            : mapper.createArrayNode();

        for (int i = 0; i < history.size(); i++) {
            if (filename.equals(history.get(i).asText())) {
                history.remove(i);
                break;
            }
        }
        history.insert(0, filename);
        if (history.size() > 5) history.remove(history.size() - 1);

        section.set("history", history);
        workspace.set(category, section);

        mapper
            .writerWithDefaultPrettyPrinter()
            .writeValue(workspaceFile.toFile(), workspace);

        return mapper.convertValue(workspace, Map.class);
    }

    /**
     * 从 BookEntity 读取 metadata（书名、页数）
     */
    private Map<String, Object> extractBookMeta(BookEntity book) {
        Map<String, Object> meta = new HashMap<>();
        String title = null;
        Integer pageCount = null;

        if (book.getMetadata() != null) {
            title = book.getMetadata().getTitle();
            pageCount = book.getMetadata().getPageCount();
        }

        meta.put("book_title", title);
        meta.put("book_page_count", pageCount);
        return meta;
    }
}
