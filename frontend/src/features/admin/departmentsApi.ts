import { fetchJson } from "@/lib/api";

export type DepartmentSummary = {
  id: string;
  label: string;
  description?: string | null;
  created_at?: number | null;
  updated_at?: number | null;
  created_by?: string | null;
  updated_by?: string | null;
};

type DepartmentListResponse = {
  departments: DepartmentSummary[];
};

type DepartmentMutationResponse = {
  ok: boolean;
  department: DepartmentSummary;
};

/** GET /api/v1/admin/departments */
export async function listDepartments(): Promise<DepartmentListResponse> {
  return fetchJson<DepartmentListResponse>("/admin/departments");
}

/** POST /api/v1/admin/departments */
export async function createDepartment(body: {
  id?: string;
  label: string;
  description?: string | null;
}): Promise<DepartmentMutationResponse> {
  return fetchJson<DepartmentMutationResponse>("/admin/departments", {
    method: "POST",
    body,
  });
}

/** PATCH /api/v1/admin/departments/{id} */
export async function updateDepartment(
  departmentId: string,
  body: { label?: string; description?: string | null },
): Promise<DepartmentMutationResponse> {
  return fetchJson<DepartmentMutationResponse>(
    `/admin/departments/${encodeURIComponent(departmentId)}`,
    {
      method: "PATCH",
      body,
    },
  );
}

/** DELETE /api/v1/admin/departments/{id} */
export async function deleteDepartment(departmentId: string): Promise<void> {
  await fetchJson<unknown>(`/admin/departments/${encodeURIComponent(departmentId)}`, {
    method: "DELETE",
  });
}
