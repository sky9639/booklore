package org.booklore.print;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.File;
import java.io.FileInputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import lombok.RequiredArgsConstructor;
import org.booklore.model.entity.BookEntity;
import org.booklore.repository.BookRepository;
import org.springframework.core.io.InputStreamResource;
import org.springframework.core.io.Resource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/**
 * 供官方 ngx-extended-pdf-viewer（pdf-reader 组件）调用
 *
 * 路由：GET /api/print/{bookId}/pdf-content
 *
 * pdf-reader.component.ts 的 print 模式中固定请求此接口：
 *   this.bookData = `${API_CONFIG.BASE_URL}/api/print/${this.bookId}/pdf-content`
 *
 * ngx-extended-pdf-viewer 会自动携带 Authorization header，
 * 所以不存在 403 问题。
 */
@RestController
@RequestMapping("/api/print")
@RequiredArgsConstructor
public class PrintContentController {

    private final BookRepository bookRepository;

    @GetMapping("/{bookId}/pdf-content")
    public ResponseEntity<Resource> getPdfContent(@PathVariable Long bookId) {
        try {
            BookEntity book = bookRepository
                .findById(bookId)
                .orElseThrow(() -> new RuntimeException("Book not found"));

            Path fullPath = book.getFullFilePath();
            if (fullPath == null) {
                return ResponseEntity.notFound().build();
            }

            // 读取 workspace.json 获取 pdf_path
            Path workspaceFile = fullPath
                .getParent()
                .resolve(".print")
                .resolve("workspace.json");
            if (!Files.exists(workspaceFile)) {
                return ResponseEntity.notFound().build();
            }

            ObjectMapper mapper = new ObjectMapper();
            com.fasterxml.jackson.databind.JsonNode ws = mapper.readTree(
                workspaceFile.toFile()
            );

            if (!ws.has("pdf_path") || ws.get("pdf_path").isNull()) {
                return ResponseEntity.notFound().build();
            }

            String pdfPath = ws.get("pdf_path").asText();
            File pdfFile = new File(pdfPath);

            if (!pdfFile.exists()) {
                return ResponseEntity.notFound().build();
            }

            InputStreamResource resource = new InputStreamResource(
                new FileInputStream(pdfFile)
            );

            return ResponseEntity.ok()
                .header(
                    HttpHeaders.CONTENT_DISPOSITION,
                    "inline; filename=\"layout_print.pdf\""
                )
                .contentLength(pdfFile.length())
                .contentType(MediaType.APPLICATION_PDF)
                .body(resource);
        } catch (Exception e) {
            return ResponseEntity.internalServerError().build();
        }
    }

    /**
     * 预览原始电子书PDF（用于PDF尺寸区域的预览按钮）
     */
    @GetMapping("/{bookId}/source-pdf-content")
    public ResponseEntity<Resource> getSourcePdfContent(@PathVariable Long bookId) {
        try {
            BookEntity book = bookRepository
                .findById(bookId)
                .orElseThrow(() -> new RuntimeException("Book not found"));

            Path fullPath = book.getFullFilePath();
            if (fullPath == null) {
                return ResponseEntity.notFound().build();
            }

            // 原始PDF路径：book.pdf
            File pdfFile = fullPath.toFile();
            if (!pdfFile.exists()) {
                return ResponseEntity.notFound().build();
            }

            // 获取书名（如果有metadata）
            String filename = "book.pdf";
            if (book.getMetadata() != null && book.getMetadata().getTitle() != null) {
                filename = book.getMetadata().getTitle() + ".pdf";
            }

            InputStreamResource resource = new InputStreamResource(
                new FileInputStream(pdfFile)
            );

            return ResponseEntity.ok()
                .header(
                    HttpHeaders.CONTENT_DISPOSITION,
                    "inline; filename=\"" + filename + "\""
                )
                .contentLength(pdfFile.length())
                .contentType(MediaType.APPLICATION_PDF)
                .body(resource);
        } catch (Exception e) {
            return ResponseEntity.internalServerError().build();
        }
    }
}
