import { http } from "./client";
import type {
  AnalyticsDashboard,
  LoginResponse,
  OutreachItem,
  OutreachStats,
  Paginated,
  PropertyDetail,
  PropertyListItem,
  ReviewRequest,
  ReviewResponse,
  SearchRequest,
  SearchResponse,
  User,
} from "./types";

export const authApi = {
  login: (email: string, password: string) =>
    http.post<LoginResponse>("/auth/login", { email, password }).then((r) => r.data),
  me: () => http.get<User>("/auth/me").then((r) => r.data),
};

export interface PropertyListParams {
  city?: string;
  property_type?: string;
  status?: string;
  min_score?: number;
  max_score?: number;
  has_phone?: boolean;
  has_email?: boolean;
  is_duplicate?: boolean;
  search?: string;
  sort?: string;
  offset?: number;
  page_size?: number;
}

export const propertiesApi = {
  list: (params: PropertyListParams) =>
    http
      .get<Paginated<PropertyListItem>>("/properties", { params })
      .then((r) => r.data),
  get: (id: string) =>
    http.get<PropertyDetail>(`/properties/${id}`).then((r) => r.data),
  review: (id: string, body: ReviewRequest) =>
    http
      .patch<ReviewResponse>(`/properties/${id}/review`, body)
      .then((r) => r.data),
};

export interface OutreachListParams {
  status?: string;
  assigned_to?: string;
  city?: string;
  min_priority?: number;
  sort?: string;
  offset?: number;
  page_size?: number;
}

export const outreachApi = {
  list: (params: OutreachListParams) =>
    http
      .get<Paginated<OutreachItem>>("/outreach", { params })
      .then((r) => r.data),
  update: (id: string, body: Record<string, unknown>) =>
    http.patch<OutreachItem>(`/outreach/${id}`, body).then((r) => r.data),
  stats: (city?: string) =>
    http
      .get<OutreachStats>("/outreach/stats", { params: { city } })
      .then((r) => r.data),
};

export const analyticsApi = {
  dashboard: () =>
    http.get<AnalyticsDashboard>("/analytics/dashboard").then((r) => r.data),
};

export const searchApi = {
  search: (body: SearchRequest) =>
    http.post<SearchResponse>("/search", body).then((r) => r.data),
};
