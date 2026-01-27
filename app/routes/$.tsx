// $ is a wildcard route that matches all unmatched routes
// 404 page can be handled here

export default function NotFound() {
  return (
    <div style={{ textAlign: 'center', padding: '2rem' }}>
      <h1>404</h1>
      <p>Page not found</p>
      <a href="/">Go home</a>
    </div>
  );
}