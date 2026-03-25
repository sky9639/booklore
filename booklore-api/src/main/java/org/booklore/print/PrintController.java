package org.booklore.print;

import java.io.File;
import java.io.FileInputStream;
import java.nio.file.Files;
import java.nio.file.Path;
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
     *
     * 注意：此方法通过 print-engine 端点更新 workspace.json，
     * print-engine 是 workspace.json 的唯一写入者。
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

            Map<String, Object> payload = new HashMap<>();
            payload.put("book_path", fullPath.toString());
            Map<String, Object> workspace = client.uploadMaterial(category, payload, file);
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
            Files.deleteIfExists(printRoot.resolve(category).resolve(filename));

            Map<String, Object> payload = new HashMap<>();
            payload.put("book_path", fullPath.toString());
            payload.put("category", category);
            payload.put("filename", filename);
            Map<String, Object> workspace = client.deleteMaterial(payload);
            return ResponseEntity.ok(workspace);
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
     *
     * 封面优先级规则：
     * - front_output.selected 优先于 cover.selected
     * - 当用户选中 cover 时，清空 front_output.selected，避免优先级冲突
     * - 前端显示封面时优先读 front_output.selected，其次才是 cover.selected
     * - 这样保证 AI 裁切生成的 front_output 始终优先于原始 cover
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
            if (fullPath == null) {
                return ResponseEntity.badRequest().body(
                    Map.of("error", "Book file path could not be resolved")
                );
            }

            Map<String, Object> payload = new HashMap<>();
            payload.put("book_path", fullPath.toString());
            payload.put("category", category);
            payload.put("filename", filename);
            Map<String, Object> workspace = client.selectMaterial(payload);
            return ResponseEntity.ok(workspace);
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
        return ResponseEntity.status(410).body(
            Map.of(
                "error",
                "This endpoint is deprecated. Use /workspace/ai-generate/start instead."
            )
        );
    }

    /**
     * 生成 Gemini 展开图（返回临时预览图和初始裁切线）
     */
    @PostMapping("/{bookId}/workspace/ai-generate/spread")
    public ResponseEntity<?> generateSpread(
        @PathVariable Long bookId,
        @RequestBody PrintRequest request
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

            Map<String, Object> payload = new HashMap<>();
            payload.put("book_path", fullPath.toString());
            payload.put(
                "book_title",
                book.getMetadata() != null && book.getMetadata().getTitle() != null
                    ? book.getMetadata().getTitle()
                    : ""
            );
            payload.put(
                "trim_size",
                request.getTrimSize() != null ? request.getTrimSize() : "A5"
            );

            double paperThickness = request.getPaperThickness() != null
                ? request.getPaperThickness()
                : 0.06;
            int pageCount = request.getPageCount() != null ? request.getPageCount() : 0;
            double spineWidthMm = request.getSpineWidthMm() != null
                ? request.getSpineWidthMm()
                : (pageCount > 0 ? pageCount * paperThickness : 4.74);
            payload.put("spine_width_mm", spineWidthMm);

            if (request.getTemplateId() != null && !request.getTemplateId().trim().isEmpty()) {
                payload.put("template_id", request.getTemplateId());
            }

            Map result = client.generateSpread(payload);
            return ResponseEntity.ok(result);
        } catch (Exception e) {
            return ResponseEntity.internalServerError().body(
                Map.of("error", e.getMessage())
            );
        }
    }

    /**
     * 保存裁切后的书脊和封底
     */
    @PostMapping("/{bookId}/workspace/ai-generate/crop")
    public ResponseEntity<?> saveAiCrop(
        @PathVariable Long bookId,
        @RequestBody Map<String, Object> body
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

            Map<String, Object> payload = new HashMap<>();
            payload.put("book_path", fullPath.toString());
            payload.put("spread_filename", body.get("spread_filename"));
            payload.put("vertical_lines", body.get("vertical_lines"));
            payload.put("horizontal_lines", body.get("horizontal_lines"));

            Map result = client.saveCroppedMaterials(payload);
            return ResponseEntity.ok(result);
        } catch (Exception e) {
            return ResponseEntity.internalServerError().body(
                Map.of("error", e.getMessage())
            );
        }
    }

    /**
     * 丢弃当前 AI 裁切草稿
     */
    @PostMapping("/{bookId}/workspace/ai-generate/discard")
    public ResponseEntity<?> discardAiCropDraft(@PathVariable Long bookId) {
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

            Map<String, Object> payload = new HashMap<>();
            payload.put("book_path", fullPath.toString());

            Map result = client.discardAiCropDraft(payload);
            return ResponseEntity.ok(result);
        } catch (Exception e) {
            return ResponseEntity.internalServerError().body(
                Map.of("error", e.getMessage())
            );
        }
    }

    @PostMapping("/{bookId}/workspace/ai-generate/history/delete")
    public ResponseEntity<?> deleteAiCropHistory(
        @PathVariable Long bookId,
        @RequestBody Map<String, Object> body
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

            Map<String, Object> payload = new HashMap<>();
            payload.put("book_path", fullPath.toString());
            payload.put("spread_filename", body.get("spread_filename"));

            Map result = client.deleteAiCropHistory(payload);
            return ResponseEntity.ok(result);
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

            // ── 组装 payload ──────────────────────────────────────────────────
            payload.put("book_title", bookTitle);
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

    /**
     * ===============================
     * 获取PDF信息（尺寸、页数等）
     * ===============================
     * POST /api/v1/print/{bookId}/pdf/info
     */
    @PostMapping("/{bookId}/pdf/info")
    public ResponseEntity<?> getPdfInfo(@PathVariable Long bookId) {
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

        Map result = client.getPdfInfo(payload);
        return ResponseEntity.ok(result);
    }

    /**
     * ===============================
     * 启动PDF格式化任务
     * ===============================
     * POST /api/v1/print/{bookId}/pdf/resize/start
     */
    @PostMapping("/{bookId}/pdf/resize/start")
    public ResponseEntity<?> startPdfResize(
        @PathVariable Long bookId,
        @RequestBody Map<String, String> request
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

        String targetSize = request.get("target_size");
        if (targetSize == null || targetSize.isEmpty()) {
            return ResponseEntity.badRequest().body(
                Map.of("error", "target_size is required")
            );
        }

        Map<String, Object> payload = new HashMap<>();
        payload.put("book_path", fullPath.toString());
        payload.put("target_size", targetSize);

        Map result = client.startPdfResize(payload);
        return ResponseEntity.ok(result);
    }

    /**
     * ===============================
     * PDF格式化进度（SSE流）
     * ===============================
     * GET /api/v1/print/{bookId}/pdf/resize/progress/{taskId}
     */
    @GetMapping("/{bookId}/pdf/resize/progress/{taskId}")
    public SseEmitter getPdfResizeProgress(
        @PathVariable Long bookId,
        @PathVariable String taskId
    ) {
        return client.streamPdfResizeProgress(taskId);
    }
}
