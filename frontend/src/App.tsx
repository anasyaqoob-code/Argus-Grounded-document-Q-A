/** Argus router — public landing, login, and the authenticated app. */

import React from "react";
import { Routes, Route, Navigate } from "react-router-dom";

import { AdminPage } from "./AdminPage";
import { AuthPage } from "./AuthPage";
import { ForgotPassword } from "./ForgotPassword";
import { GoogleCallback } from "./GoogleCallback";
import { LandingPage } from "./LandingPage";
import { MainApp } from "./MainApp";
import { RequireAuth } from "./RequireAuth";
import { ResetPassword } from "./ResetPassword";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/login" element={<AuthPage />} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />
      <Route path="/auth/google/callback" element={<GoogleCallback />} />
      <Route
        path="/app"
        element={
          <RequireAuth>
            <MainApp />
          </RequireAuth>
        }
      />
      <Route
        path="/admin"
        element={
          <RequireAuth>
            <AdminPage />
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}