export const compact = (n) => n >= 1000 ? `${(n / 1000).toFixed(1)}k` : n
