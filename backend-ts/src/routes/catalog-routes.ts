import { Router } from "express";
import { query } from "../db/pool.js";

export const catalogRoutes = Router();

catalogRoutes.get("/api/v1/tipos-vehiculo", async (_req, res, next) => {
  try {
    const rows = await query<{ id: number; nombre: string; descripcion: string | null }>(
      `
      SELECT id, nombre, descripcion
      FROM tipos_vehiculo
      ORDER BY nombre ASC
      `
    );
    res.json(rows);
  } catch (error) {
    next(error);
  }
});

catalogRoutes.get("/api/v1/posiciones-luz", (_req, res) => {
  res.json([
    { code: "cruce", description: "Luz de cruce" },
    { code: "largo", description: "Luz larga" },
    { code: "cruce_y_largo", description: "Luz de cruce y larga" },
    { code: "antiniebla", description: "Luz antiniebla" },
    { code: "todos", description: "Aplica a todas las posiciones" }
  ]);
});

catalogRoutes.get("/api/v1/tipos-sistema-optico", (_req, res) => {
  res.json([
    { code: "lupa_proyector", description: "Lupa o proyector" },
    { code: "reflector_abierto", description: "Reflector abierto" },
    { code: "ambos", description: "Compatible con ambos" }
  ]);
});
