import { redirect } from "next/navigation";
export default function Home() {
  // Auth state lives in the browser's tab-scoped Cognito session storage.
  // The login route resolves that state and forwards signed-in users.
  redirect("/login");
}
