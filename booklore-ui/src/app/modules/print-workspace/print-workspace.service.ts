import {inject, Injectable} from '@angular/core';
import {HttpClient} from '@angular/common/http';
import {Observable} from 'rxjs';

interface PrintRequest {
  paperThickness: number;
  pageCount: number;
  spineMode: 'auto' | 'manual';
  backMode: 'auto' | 'manual';
}

@Injectable({
  providedIn: 'root'
})
export class PrintWorkspaceService {
  private readonly http = inject(HttpClient);

  generatePreview(bookId: number, request: PrintRequest): Observable<any> {
    return this.http.post<any>(`/api/print/${bookId}/preview`, request);
  }

  generatePdf(bookId: number, request: PrintRequest): Observable<any> {
    return this.http.post<any>(`/api/print/${bookId}/pdf`, request);
  }
}

