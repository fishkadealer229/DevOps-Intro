package main

import (
	"net/http"

	"github.com/go-chi/chi/v5"
)

func securityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Security-Policy", "default-src 'none'; style-src 'self'; script-src 'self';")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("X-Frame-Options", "DENY")
		w.Header().Set("X-XSS-Protection", "1; mode=block")
		next.ServeHTTP(w, r)
	})
}

func main() {
	router := chi.NewRouter()
	router.Use(securityHeaders) // центральный middleware — все маршруты
	http.ListenAndServe(":8080", router)
}