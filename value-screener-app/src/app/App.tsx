import { RouterProvider } from "react-router";
import { router } from "./routes";
import { DataProvider } from "./DataContext";
import { AuthProvider } from "./AuthContext";

export default function App() {
  return (
    <AuthProvider>
      <DataProvider>
        <RouterProvider router={router} />
      </DataProvider>
    </AuthProvider>
  );
}
