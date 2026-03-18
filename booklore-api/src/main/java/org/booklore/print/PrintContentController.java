package org.booklore.print;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileNotFoundException;
import java.nio.file.Files;
import java.nio.file.Path;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.booklore.model.entity.BookEntity;
import org.booklore.repository.BookRepository;
import org.springframework.core.io.InputStreamResource;
import org.springframework.core.io.Resource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/**
 * PDF内容服务控制器
 * 供ngx-extended-pdf-viewer（pdf-reader组件）调用
 *
 * 版本：V1.1
 * 创建日期：2026-03-18
 *
 * 功能：
 *   1. 提供生成的印刷PDF内容（/pdf-content）
 *   2. 提供原始电子书PDF内容（/source-pdf-content）
 *
 * 路由：
 *   - GET /api/print/{bookId}/pdf-content - 印刷PDF
 *   - GET /api/print/{bookId}/source-pdf-content - 原始PDF
 *
 * 说明：
 *   ngx-extended-pdf-viewer会自动携带Authorization header，
 *   因此不存在403权限问题
 */
@Slf4j
@RestController
@RequestMapping("/api/print")
@RequiredArgsConstructor
public class PrintContentController {

    private final BookRepository bookRepository;

    /**
     * 获取生成的印刷PDF内容
     *
     * @param bookId 书籍ID
     * @return PDF文件流或404
     */
    @GetMapping("/{bookId}/pdf-content")
    public ResponseEntity<Resource> getPdfContent(@PathVariable Long bookId) {
        try {
            // 查询书籍
            BookEntity book = bookRepository
                .findById(bookId)
                .orElseThrow(() -> new RuntimeException("Book not found: " + bookId));

            Path fullPath = book.getFullFilePath();
            if (fullPath == null) {
                log.warn("Book {} has no file path", bookId);
                return ResponseEntity.notFound().build();
            }

            // 读取workspace.json获取pdf_path
            Path workspaceFile = fullPath
                .getParent()
                .resolve(".print")
                .resolve("workspace.json");

            if (!Files.exists(workspaceFile)) {
                log.warn("Workspace file not found for book {}: {}", bookId, workspaceFile);
                return ResponseEntity.notFound().build();
            }

            ObjectMapper mapper = new ObjectMapper();
            com.fasterxml.jackson.databind.JsonNode ws = mapper.readTree(
                workspaceFile.toFile()
            );

            if (!ws.has("pdf_path") || ws.get("pdf_path").isNull()) {
                log.warn("No pdf_path in workspace for book {}", bookId);
                return ResponseEntity.notFound().build();
            }

            String pdfPath = ws.get("pdf_path").asText();
            File pdfFile = new File(pdfPath);

            if (!pdfFile.exists()) {
                log.warn("Print PDF file not found: {}", pdfPath);
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

        } catch (FileNotFoundException e) {
            log.error("PDF file not found for book {}", bookId, e);
            return ResponseEntity.notFound().build();
        } catch (Exception e) {
            log.error("Error serving print PDF for book {}", bookId, e);
            return ResponseEntity.internalServerError().build();
        }
    }

    /**
     * 获取原始电子书PDF内容（用于PDF尺寸区域的预览按钮）
     *
     * @param bookId 书籍ID
     * @return PDF文件流或404
     */
    @GetMapping("/{bookId}/source-pdf-content")
    public ResponseEntity<Resource> getSourcePdfContent(@PathVariable Long bookId) {
        try {
            // 查询书籍
            BookEntity book = bookRepository
                .findById(bookId)
                .orElseThrow(() -> new RuntimeException("Book not found: " + bookId));

            Path fullPath = book.getFullFilePath();
            if (fullPath == null) {
                log.warn("Book {} has no file path", bookId);
                return ResponseEntity.notFound().build();
            }

            // 原始PDF路径：book.pdf
            File pdfFile = fullPath.toFile();
            if (!pdfFile.exists()) {
                log.warn("Source PDF file not found: {}", fullPath);
                return ResponseEntity.notFound().build();
            }

            // 获取书名（如果有metadata）
            String filename = "book.pdf";
            if (book.getMetadata() != null && book.getMetadata().getTitle() != null) {
                // 清理文件名中的非法字符
                String title = book.getMetadata().getTitle()
                    .replaceAll("[\\\\/:*?\"<>|]", "_");
                filename = title + ".pdf";
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

        } catch (FileNotFoundException e) {
            log.error("Source PDF file not found for book {}", bookId, e);
            return ResponseEntity.notFound().build();
        } catch (Exception e) {
            log.error("Error serving source PDF for book {}", bookId, e);
            return ResponseEntity.internalServerError().build();
        }
    }
}
