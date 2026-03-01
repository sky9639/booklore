import { Component, OnInit } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

@Component({
  standalone: true,
  selector: 'app-print-workspace',
  templateUrl: './print-workspace.component.html',
  styleUrls: ['./print-workspace.component.scss'],
  imports: [CommonModule, FormsModule]
})
export class PrintWorkspaceComponent implements OnInit {

  bookId!: number;

  // ===== 状态 =====
  state = {
    bookName: '',
    trimSize: 'A5',

    pageCount: 100,
    paperThickness: 0.06,
    spineWidth: 0,

    coverUrl: null as string | null,
    coverPage: 1,

    previewUrl: null as string | null,
    pdfPath: null as string | null
  };

  // ===== 额外控制状态 =====
  loading = false;
  showLightbox = false;

  spineMode: 'auto' | 'manual' = 'auto';
  backMode: 'auto' | 'manual' = 'auto';

  previewData: any = null;

  constructor(
    private route: ActivatedRoute,
    private http: HttpClient
  ) {}

  ngOnInit() {
    this.route.params.subscribe(p => {
      this.bookId = +p['bookId'];
      this.recalculateSpine();
      this.loadBookInfo();
    });
  }

  // ===== 返回按钮 =====
  goBack() {
    history.back();
  }

  // ===== 载入书籍信息 =====
  loadBookInfo() {
    this.http.get<any>(`/api/books/${this.bookId}`)
      .subscribe(res => {
        this.state.bookName = res.title ?? '';
        this.state.pageCount = res.pageCount ?? this.state.pageCount;
        this.recalculateSpine();
      });
  }

  // ===== 自动计算书脊宽度 =====
  recalculateSpine() {
    if (!this.state.pageCount || !this.state.paperThickness) return;

    this.state.spineWidth =
      +(this.state.pageCount * this.state.paperThickness).toFixed(3);
  }

  // ===== 生成预览 =====
  generatePreview() {

    this.loading = true;
    this.state.previewUrl = null;

    this.http.post<any>(
      `/api/print/${this.bookId}/preview`,
      {
        paperThickness: this.state.paperThickness,
        pageCount: this.state.pageCount,
        spineMode: this.spineMode,
        backMode: this.backMode
      }
    ).subscribe({
      next: res => {

        if (res.preview_png) {
          this.state.previewUrl = res.preview_png;
        }

        this.previewData = res;
        this.loading = false;
      },
      error: err => {
        console.error(err);
        this.loading = false;
      }
    });
  }

  // ===== 生成 PDF =====
  generatePdf() {

    this.loading = true;

    this.http.post<any>(
      `/api/print/${this.bookId}/pdf`,
      {
        paperThickness: this.state.paperThickness,
        pageCount: this.state.pageCount,
        spineMode: this.spineMode,
        backMode: this.backMode
      }
    ).subscribe({
      next: res => {

        if (res.pdf_path) {
          this.state.pdfPath = res.pdf_path;
        }

        this.loading = false;
      },
      error: err => {
        console.error(err);
        this.loading = false;
      }
    });
  }

  // ===== 下载 PDF =====
  downloadPdf() {
    if (!this.state.pdfPath) return;

    window.open(
      `/api/print/pdf?path=${encodeURIComponent(this.state.pdfPath)}`,
      '_blank'
    );
  }

  // ===== Lightbox =====
  openLightbox() {
    this.showLightbox = true;
  }

  closeLightbox() {
    this.showLightbox = false;
  }

  handleCoverError() {
    this.state.coverUrl = null;
  }
}