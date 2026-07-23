"use server";

import { redirect } from "next/navigation";

import { BackendError, performLogin } from "@/lib/auth";

export interface LoginFormState {
  error?: string;
}

export async function loginAction(
  _prevState: LoginFormState,
  formData: FormData,
): Promise<LoginFormState> {
  const email = formData.get("email");
  const password = formData.get("password");

  if (typeof email !== "string" || typeof password !== "string" || !email || !password) {
    return { error: "Email and password are required." };
  }

  try {
    await performLogin(email, password);
  } catch (error) {
    if (error instanceof BackendError) {
      return { error: "Invalid email or password." };
    }
    throw error;
  }

  redirect("/dashboard");
}
