try {
  rs.status();
} catch (error) {
  rs.initiate({ _id: "rs0", members: [{ _id: 0, host: "mongo:27017" }] });
}

for (let i = 0; i < 60; i += 1) {
  if (db.hello().isWritablePrimary) quit(0);
  sleep(500);
}
quit(1);
